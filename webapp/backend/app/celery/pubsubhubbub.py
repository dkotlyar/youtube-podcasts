import base64
import secrets
from datetime import timedelta, datetime
from os import environ
from hashlib import sha1
import hmac

import requests
from sqlalchemy import and_

from app.celery import celery


def generate_secret():
    """
    Generate random secret key for hub verification
    Returns:
        Secret token (string)
    """
    return secrets.token_urlsafe(16)


def generate_signature(body: bytes, key: str):
    """
    Generate HMAC SHA1 signature for body
    Returns:
        Signature (hex string)
    """
    hashed = hmac.new(key.encode('utf8'), body, sha1)
    _digest = hashed.digest()
    return ''.join(map(lambda b: f'{b:x}', _digest))


def resubscribe(ctx, time_delta=None):
    from app import db
    from app.models.source_channels import SourceChannel

    with ctx:
        if not time_delta:
            time_delta = timedelta(days=1)

        resubscribe_channels = SourceChannel.query.filter(and_(
            SourceChannel.pubsubhubbub_mode == 'subscribe',
            SourceChannel.pubsubhubbub_expires_at <= datetime.now() + time_delta
        ))

        for channel in resubscribe_channels:
            channel.verify_token = generate_secret()
            db.session.add(channel)
            subscribe.delay(channel.channel_id, channel.verify_token, channel.pubsubhubbub_mode)

        db.session.commit()


@celery.task(name='backend.pubsubhubbub.subscribe')
def subscribe(channel_id: str, verify_token: str = None, secret: str = None, mode_subscribe: str = 'subscribe', lease_seconds: int = 1e6):
    """
    Create subscribe request to pubsubhubbub.appspot.com hub
    """
    assert mode_subscribe in ['subscribe', 'unsubscribe']

    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    return requests.post('https://pubsubhubbub.appspot.com/subscribe', headers=headers, data={
        'hub.callback': f'{environ.get("BASE_URL")}/hooks/new/{channel_id}',
        'hub.mode': mode_subscribe,
        'hub.topic': f'https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}',
        'hub.verify': 'sync',
        'hub.lease_seconds': lease_seconds,
        'hub.verify_token': verify_token,
        'hub.secret': secret,
    })
