# coding: utf-8
import time
from threading import Thread
from collections import defaultdict
from uuid import uuid4

from ..exceptions import CreationException
from ..config import config
from ..logger import log


class VirtualMachinesPool(object):
    pool = list()
    using = list()

    def __str__(self):
        return str(self.pool)

    @classmethod
    def remove_vm(cls, vm):
        if vm in list(cls.using):
            try:
                cls.using.remove(vm)
            except ValueError:
                pass
        if vm in list(cls.pool):
            try:
                cls.pool.remove(vm)
            except ValueError:
                pass

    @classmethod
    def add_vm(cls, vm, to=None):
        if to is None:
            to = cls.pool
        to.append(vm)

    @classmethod
    def free(cls):
        log.info("deleting using machines")
        for vm in list(cls.using):
            cls.using.remove(vm)
            vm.delete()
        log.info("deleting pool")
        for vm in list(cls.pool):
            cls.pool.remove(vm)
            vm.delete()

    @classmethod
    def count(cls):
        return len(cls.pool) + len(cls.using)

    @classmethod
    def can_produce(cls):
        max_count = 0

        if config.USE_KVM:
            max_count += config.KVM_MAX_VM_COUNT
        if config.USE_OPENSTACK:
            max_count += config.OPENSTACK_MAX_VM_COUNT

        can_produce = max_count - cls.count()

        return can_produce if can_produce >= 0 else 0

    @classmethod
    def has(cls, platform):
        for vm in cls.pool:
            if vm.platform == platform and vm.ready and not vm.checking:
                return True

        return False

    @classmethod
    def get(cls, platform):
        for vm in sorted(cls.pool, key=lambda v: v.creation_time):
            log.info("Getting VM %s has ready property is %s and checking property is %s" % (vm.name, vm.ready, vm.checking))
            if vm.platform == platform and vm.ready and not vm.checking:
                if vm.vm_is_ready():
                    cls.pool.remove(vm)
                    cls.using.append(vm)
                    return vm
                else:
                    cls.pool.remove(vm)
                    vm.delete()

    @classmethod
    def count_virtual_machines(cls, it):
        result = defaultdict(int)
        for vm in it:
            result[vm.platform] += 1

        return result

    @classmethod
    def pooled_virtual_machines(cls):
        return cls.count_virtual_machines(cls.pool)

    @classmethod
    def using_virtual_machines(cls):
        return cls.count_virtual_machines(cls.using)

    @classmethod
    def add(cls, origin_name, prefix=None, to=None):
        from ..platforms import Platforms

        if not cls.can_produce():
            raise CreationException("maximum count of virtual machines already running")

        if to is None:
            to = cls.using

        if prefix is None:
            prefix = "ondemand-{}".format(uuid4())

        origin = Platforms.get(origin_name)
        clone = origin.make_clone(origin, prefix)

        cls.add_vm(clone, to)

        try:
            clone.create()
        except Exception as e:
            log.error(e)
            clone.delete()
            try:
                to.remove(clone)
            except ValueError:
                pass
            return

        return clone

    @classmethod
    def preload(cls, origin_name, prefix=None):
        return cls.add(origin_name, prefix, to=cls.pool)

    @classmethod
    def return_vm(cls, vm):
        cls.using.remove(vm)
        cls.pool.append(vm)

    @property
    def info(self):
        def print_view(lst):
            return [{"name": l.name, "ip": l.ip, "ready": l.ready, "checking": l.checking} for l in lst]
        return {
            "pool": {
                'count': self.pooled_virtual_machines(),
                'list': print_view(self.pool),
            },
            "using": {
                'count': self.using_virtual_machines(),
                'list': print_view(self.using),
            },
            "can_produce": self.can_produce()
        }


class VirtualMachinesPoolPreloader(Thread):
    def __init__(self, pool):
        Thread.__init__(self)
        self.running = True
        self.daemon = True
        self.pool = pool

    def run(self):
        while self.running:
            if self.pool.can_produce():
                platform = self.need_load()
                if platform is not None:
                    log.info("VM for preloaded was found. Preloading vm for platform %s " % platform)
                    self.pool.preload(platform, "preloaded-{}".format(uuid4()))

            time.sleep(config.PRELOADER_FREQUENCY)

    def need_load(self):
        using = [vm for vm in self.pool.using if 'preloaded' in vm.prefix] if self.pool.using is not [] else []
        already_have = self.pool.count_virtual_machines(self.pool.pool + using)
        platforms = {}

        if config.USE_KVM:
            platforms.update(config.KVM_PRELOADED)
        if config.USE_OPENSTACK:
            platforms.update(config.OPENSTACK_PRELOADED)

        for platform, need in platforms.iteritems():
            have = already_have.get(platform, 0)
            if need > have:
                return platform

    def stop(self):
        self.running = False
        self.join()
        log.info("Preloader stopped")


class VirtualMachineChecker(Thread):
    def __init__(self, pool):
        Thread.__init__(self)
        self.running = config.VM_CHECK
        self.daemon = True
        self.pool = pool

    def run(self):
        while self.running:
            self.fix_broken_vm()
            time.sleep(config.VM_CHECK_FREQUENCY)

    def fix_broken_vm(self):
        for vm in self.pool.pool:
            vm.checking = True
            log.info("Check for {clone} with {ip}:{port}".format(clone=vm.name, ip=vm.ip, port=config.SELENIUM_PORT))
            if vm.ready:
                if not vm.vm_is_ready():
                    try:
                        vm.rebuild()
                    except Exception as e:
                        log.error(e)
                        vm.delete()
                        self.pool.remove(vm)
            vm.checking = False

    def stop(self):
        self.running = False
        self.join(1)
        log.info("VMChecker stopped")


pool = VirtualMachinesPool()
