# coding=utf-8
import os

import datetime
from oauth2client.client import OAuth2Credentials
from firetool_commands.common import PlainFirebaseRoot
from firetool_commands.configstore import Configstore

client_id = os.environ.get(
    'FIREBASE_CLIENT_ID', '563584335869-fgrhgmd47bqnekij5i8b5pr03ho849e6.apps.googleusercontent.com')
client_secret = os.environ.get('FIREBASE_CLIENT_SECRET', 'j9iVZfS8kkCEFUPaAeJV0sAi')

google_origin = os.environ.get(
    'FIREBASE_TOKEN_URL', os.environ.get('FIREBASE_GOOGLE_URL', 'https://www.googleapis.com'))


def get_cred():
    config_store = Configstore('firebase-tools')
    return OAuth2Credentials(
        config_store['tokens.access_token'],
        client_secret=client_secret,
        client_id=client_id,
        token_expiry=datetime.datetime.fromtimestamp(config_store['tokens.expires_at']/1000.0),
        refresh_token=config_store['tokens.refresh_token'], token_uri=google_origin + '/oauth2/v3/token',
        user_agent='firetool')


def get_firebase(project):
    c = get_cred()
    firebase = PlainFirebaseRoot('https://{project}.firebaseio.com/'.format(project=project))
    firebase.set_credentials(c)

    return firebase
