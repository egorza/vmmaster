# coding: utf-8

import time
import logging
from Queue import Queue, Empty

from twisted.web.wsgi import WSGIResource
from twisted.web.server import Site
from twisted.web.resource import Resource
from twisted.python.failure import Failure
from twisted.python.threadpool import ThreadPool
from twisted.internet.defer import inlineCallbacks, Deferred, TimeoutError
from twisted.internet.threads import deferToThread

from app import create_app
from http_proxy import ProxyResource, HTTPChannelWithClient
from core.config import config

log = logging.getLogger(__name__)


def _block_on(d, timeout=None):
    _q = Queue()
    if not isinstance(d, Deferred):
        return None
    d.addBoth(_q.put)
    try:
        ret = _q.get(timeout is not None, timeout)
    except Empty:
        raise TimeoutError
    if isinstance(ret, Failure):
        ret.raiseException()
    else:
        return ret


class RootResource(Resource):
    def __init__(self, fallback_resource):
        Resource.__init__(self)
        self.fallback_resource = fallback_resource

    def getChildWithDefault(self, path, request):
        if path in self.children:
            return self.children[path]

        request.postpath.insert(0, path)
        return self.fallback_resource


class VMMasterServer(object):
    def __init__(self, reactor, port):
        self.reactor = reactor
        self.app = create_app()
        self.thread_pool = ThreadPool(maxthreads=config.THREAD_POOL_MAX)
        self.thread_pool.start()
        wsgi_resource = WSGIResource(self.reactor, self.thread_pool, self.app)

        root_resource = RootResource(wsgi_resource)
        root_resource.putChild("proxy", ProxyResource(self.app))
        site = Site(root_resource)
        site.protocol = HTTPChannelWithClient
        self.bind = self.reactor.listenTCP(port, site)
        log.info('Server is listening on %s ...' % port)

    def run(self):
        self.reactor.addSystemEventTrigger('before', 'shutdown',
                                           self.before_shutdown)
        self.reactor.run()
        del self

    def __del__(self):
        d = self.bind.stopListening()
        _block_on(d, 20)
        self.app.cleanup()
        self.thread_pool.stop()

    def wait_for_end_active_sessions(self):
        active_sessions = self.app.sessions.active()

        def wait_for():
            while active_sessions:
                for session in active_sessions:
                    if session.status in ('failed', 'succeed'):
                        active_sessions.remove(session)

                time.sleep(1)
                log.info("Wait for end %s active session[s]:"
                         " %s" % (len(active_sessions), active_sessions))

        return deferToThread(wait_for, self).addBoth(
            lambda i: log.info("All active sessions has been completed")
        )

    @inlineCallbacks
    def before_shutdown(self):
        self.app.running = False
        yield self.wait_for_end_active_sessions()
