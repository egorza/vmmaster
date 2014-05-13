import httplib
import copy
import time
import base64

from twisted.internet.threads import deferToThread
from twisted.web.proxy import Proxy
from twisted.web.http import Request, HTTPFactory

from vmmaster.core.server import commands
from vmmaster.core.config import config
from vmmaster.core.logger import log
from vmmaster.utils.utils import write_file


class RequestHandler(Request):
    _headers = None
    _body = None

    _reply_code = None
    _reply_headers = None
    _reply_body = None

    _log_step = None
    _session_id = None

    def __init__(self, *args):
        Request.__init__(self, *args)
        self.clone_factory = self.channel.factory.clone_factory
        self.sessions = self.channel.factory.sessions
        self.database = self.channel.factory.database

    @property
    def headers(self):
        """get headers dictionary"""
        if self._headers:
            return self._headers

        self._headers = self.getAllHeaders()
        return self._headers

    @property
    def body(self):
        """get request body."""
        if self._body:
            return self._body

        data = copy.copy(self.content)

        if self.getHeader('Content-Length') is None:
            self._body = None
        else:
            content_length = int(self.getHeader('Content-Length'))
            self._body = data.read(content_length)

        del data
        return self._body

    @property
    def session_id(self):
        if self._session_id:
            return self._session_id

        self._session_id = commands.get_session_id(self.path)
        return self._session_id

    def requestReceived(self, command, path, version):
        Request.requestReceived(self, command, path, version)
        if self.session_id:
            self._log_step = self.database.createLogStep(
                session_id=self.session_id,
                control_line="%s %s %s" % (command, path, version),
                body=str(self.body),
                time=time.time())

        self.processRequest()

    def finish(self):
        self.perform_reply()
        Request.finish(self)

    def handle_exception(self, failure):
        tb = failure.getTraceback()
        log.error(tb)
        self.form_reply(code=500, headers={}, body=tb)
        session = self.database.getSession(self.session_id)
        session.status = "failed"
        session.error = tb
        self.database.update(session)
        return self

    def try_screenshot(self):
        words = ["url", "click", "execute", "keys"]
        parts = self.path.split("/")
        if set(words) & set(parts) or parts[-1] == "session":
            clone = self.sessions.get_clone(self.session_id)
            return commands.take_screenshot(clone.get_ip(), 9000)

    def processRequest(self):
        method = getattr(self, "do_" + self.method)
        d = deferToThread(method)
        d.addErrback(lambda failure: RequestHandler.handle_exception(self, failure))
        d.addBoth(RequestHandler.finish)

    def make_request(self, method, url, headers, body):
        """ Make request to selenium-server-standalone
            and return the response. """
        clone = self.sessions.get_clone(self.session_id)
        conn = httplib.HTTPConnection("{ip}:{port}".format(ip=clone.get_ip(), port=config.SELENIUM_PORT))
        conn.request(method=method, url=url, headers=headers, body=body)

        clone.get_timer().restart()

        response = conn.getresponse()

        if response.getheader('Content-Length') is None:
            response_body = None
        else:
            content_length = int(response.getheader('Content-Length'))
            response_body = response.read(content_length)

        conn.close()

        return response.status, dict(x for x in response.getheaders()), response_body

    def form_reply(self, code, headers, body):
        """ Send reply to client. """
        # reply code
        self._reply_code = code

        # reply headers
        self._reply_headers = {}
        for keyword, value in headers.items():
            self._reply_headers[keyword] = value

        # reply body
        self._reply_body = body

    def perform_reply(self):
        """ Perform reply to client. """
        if self.session_id:
            self.database.createLogStep(
                session_id=self.session_id,
                control_line="%s %s" % (self.clientproto, self._reply_code),
                body=str(self._reply_body),
                time=time.time())

        self.setResponseCode(self._reply_code)

        for keyword, value in self._reply_headers.items():
            self.setHeader(keyword, value)

        self.write(self._reply_body)

    def swap_session(self, desired_session):
        self.body = commands.set_body_session_id(self.body, desired_session)
        self.path = commands.set_path_session_id(self.path, desired_session)
        if self.body:
            self.headers['content-length'] = len(self.body)

    def transparent(self, method):
        self.swap_session(self.sessions.get_selenium_session(self.session_id))
        code, headers, response_body = self.make_request(method, self.path, self.headers, self.body)
        self.swap_session(self.session_id)
        self.form_reply(code, headers, response_body)

    def do_POST(self):
        """POST request."""
        if self.path.split("/")[-1] == "session":
            commands.create_session(self)
        else:
            self.transparent("POST")

        screenshot = self.try_screenshot()
        if screenshot:
            if self._log_step:
                path = config.SCREENSHOTS_DIR + "/" + str(self.session_id) + "/" + str(self._log_step.id) + ".png"
                write_file(path, base64.b64decode(screenshot))
                self._log_step.screenshot = path
                self.database.update(self._log_step)
        return self

    def do_GET(self):
        """GET request."""
        self.transparent("GET")
        return self

    def do_DELETE(self):
        """DELETE request."""
        if self.path.split("/")[-2] == "session":
            commands.delete_session(self)
        else:
            self.transparent("DELETE")
        return self


class RequestProxy(Proxy):
    requestFactory = RequestHandler


class ProxyFactory(HTTPFactory):
    log = lambda *args: None
    protocol = RequestProxy

    def __init__(self, clone_factory, sessions, database):
        HTTPFactory.__init__(self)
        self.clone_factory = clone_factory
        self.sessions = sessions
        self.database = database