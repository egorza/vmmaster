# coding: utf-8

from flask import Blueprint, jsonify
import helpers
from ..core.auth.api_auth import auth

api = Blueprint('api', __name__)


def render_json(result, code=200):
    response = dict()
    response['metacode'] = code
    response['result'] = result
    return jsonify(response)


@api.route('/status')
def status():
    return render_json({
        'platforms': helpers.get_platforms(),
        'sessions': helpers.get_sessions(),
        'queue': helpers.get_queue(),
        'pool': helpers.get_pool()
    })


@api.route('/platforms')
def platforms():
    return render_json({'platforms': helpers.get_platforms()})


@api.route('/sessions')
def sessions():
    return render_json({'sessions': helpers.get_sessions()})


@api.route('/queue')
def queue():
    return render_json({'queue': helpers.get_queue()})


@api.route('/pool')
def pool():
    return render_json({'pool': helpers.get_pool()})


@api.route('/session/<int:session_id>')
def session(session_id):
    _session = helpers.get_session(session_id)
    if _session:
        return render_json(_session.info)
    else:
        return render_json("Session %s not found" % session_id, 404)


@api.route('/session/<string:session_id>/stop', methods=['POST'])
def stop_session(session_id):
    _session = helpers.get_session(session_id)
    if _session:
        _session.close()
        return render_json("Session %s closed successfully" % session_id, 200)
    else:
        return render_json("Session %s not found" % session_id, 404)


@api.route('/user/<int:user_id>', methods=['GET'])
@auth.login_required
def user_info(user_id):
    user = helpers.get_user(user_id)
    if user:
        return render_json(user.info)
    else:
        return render_json("User %s not found" % user_id, 404)


@api.route('/user/<int:user_id>/regenerate_token', methods=['POST'])
@auth.login_required
def regenerate_token(user_id):
    updated_user = helpers.regenerate_user_token(user_id)
    if updated_user:
        return render_json("Token for the user %s regenerated successfully "
                           % updated_user.username, 200)
    else:
        return render_json("User %s not found" % user_id, 404)
