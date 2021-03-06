# coding: utf-8

import json
from uuid import uuid4
from datetime import datetime

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, Sequence, String, Enum, \
    ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship, backref

from flask import current_app

Base = declarative_base()


class FeaturesMixin(object):
    def add(self):
        current_app.database.add(self)

    def save(self):
        current_app.database.update(self)

    def refresh(self):
        current_app.database.refresh(self)


class SessionLogSubStep(Base, FeaturesMixin):
    __tablename__ = 'sub_steps'

    id = Column(Integer, Sequence('sub_steps_id_seq'), primary_key=True)
    session_log_step_id = Column(
        Integer, ForeignKey(
            'session_log_steps.id', ondelete='CASCADE'),
        index=True
    )
    control_line = Column(String)
    body = Column(String)
    created = Column(DateTime, default=datetime.now)

    def __init__(self, control_line, body=None, parent_id=None):
        self.control_line = control_line
        self.body = body
        if parent_id:
            self.session_log_step_id = parent_id
        self.add()


class SessionLogStep(Base, FeaturesMixin):
    __tablename__ = 'session_log_steps'

    id = Column(Integer, Sequence('session_log_steps_id_seq'),
                primary_key=True)
    session_id = Column(
        Integer, ForeignKey('sessions.id', ondelete='CASCADE'), index=True
    )
    control_line = Column(String)
    body = Column(String)
    screenshot = Column(String)
    created = Column(DateTime, default=datetime.now)

    # Relationships
    sub_steps = relationship(
        SessionLogSubStep,
        cascade="all, delete",
        backref=backref(
            "session_log_step",
            single_parent=True
        )
    )

    def __init__(self, control_line, body=None, session_id=None, created=None):
        self.control_line = control_line
        self.body = body
        if session_id:
            self.session_id = session_id
        if created:
            self.created = created
        self.add()

    def add_sub_step(self, control_line, body):
        return SessionLogSubStep(control_line=control_line,
                                 body=body,
                                 parent_id=self.id)


class Session(Base, FeaturesMixin):
    __tablename__ = 'sessions'

    id = Column(Integer, Sequence('session_id_seq'), primary_key=True)
    user_id = Column(ForeignKey('users.id', ondelete='SET NULL'), default=1)
    endpoint_ip = Column(String)
    endpoint_name = Column(String)
    name = Column(String)
    dc = Column(String)
    selenium_session = Column(String)
    take_screenshot = Column(Boolean)
    run_script = Column(String)
    created = Column(DateTime, default=datetime.now)
    modified = Column(DateTime, default=datetime.now)
    deleted = Column(DateTime)

    # State
    status = Column(Enum('unknown', 'running', 'succeed', 'failed', 'waiting',
                         name='status', native_enum=False), default='waiting')
    reason = Column(String)
    error = Column(String)
    timeouted = Column(Boolean, default=False)
    closed = Column(Boolean, default=False)

    # Relationships
    session_steps = relationship(
        SessionLogStep,
        cascade="all, delete",
        backref=backref(
            "session",
            enable_typechecks=False,
            single_parent=True
        )
    )

    def set_user(self, username):
        self.user = current_app.database.get_user(username=username)

    def __init__(self, name=None, dc=None):
        if name:
            self.name = name

        if dc:
            self.dc = json.dumps(dc)

            if dc.get("name", None) and not self.name:
                self.name = dc["name"]

            if dc.get("user", None):
                self.set_user(dc["user"])
            if dc.get("takeScreenshot", None):
                self.take_screenshot = True
            if dc.get("runScript", None):
                self.run_script = json.dumps(dc["runScript"])

        self.add()

        if not self.name:
            self.name = "Unnamed session " + str(self.id)
            self.save()

    @property
    def platform(self):
        return json.loads(self.dc).get("platform", None)

    def add_session_step(self, control_line, body=None, created=None):
        return SessionLogStep(control_line=control_line,
                              body=body,
                              session_id=self.id,
                              created=created)


class User(Base, FeaturesMixin):
    __tablename__ = 'users'

    @staticmethod
    def generate_token():
        return str(uuid4())

    def regenerate_token(self):
        self.token = User.generate_token()
        self.save()
        return self.token

    @property
    def info(self):
        return {
            "username": self.username,
        }

    id = Column(Integer, primary_key=True)
    username = Column(String(length=30), unique=True, nullable=False)
    password = Column(String(128))
    allowed_machines = Column(Integer, default=1)
    group_id = Column(ForeignKey('user_groups.id', ondelete='SET DEFAULT'),
                      nullable=True,
                      default=1)
    is_active = Column(Boolean, default=True)
    date_joined = Column(DateTime, default=datetime.now)
    last_login = Column(DateTime)
    token = Column(String(50), nullable=True, default=generate_token)
    max_stored_sessions = Column(Integer, default=100)

    # Relationships
    sessions = relationship(Session, backref="user", passive_deletes=True)


class UserGroup(Base):
    __tablename__ = 'user_groups'

    id = Column(Integer, primary_key=True)
    name = Column(String(length=20), unique=True, nullable=False)

    # Relationships
    users = relationship(User, backref="group", passive_deletes=True)


class Platform(Base):
    __tablename__ = 'platforms'

    id = Column(Integer, primary_key=True)
    name = Column(String(length=100), nullable=False)
    node = Column(String(length=100), nullable=False)

    def __init__(self, name, node):
        self.name = name
        self.node = node
