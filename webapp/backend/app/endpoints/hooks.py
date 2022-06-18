from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from werkzeug.exceptions import BadRequest
from xmltodict import parse

from app.celery import media_manager
from app.celery.pubsubhubbub import generate_signature
from app.models import db
from app.models.source_channels import SourceChannel
from app.models.video import YoutubeVideo

hooks = Blueprint('hooks', __name__)


@hooks.route('/new/<string:channel_id>', methods=['GET'])
def subscribe(channel_id: str):
    """Accept subscription to PubSubHubbub"""
    # search source channel in db
    source_channel = SourceChannel.query.filter_by(channel_id=channel_id).first_or_404()

    # check request args for required arguments
    for arg in ['hub.lease_seconds', 'hub.mode', 'hub.challenge', 'hub.verify_token']:
        if arg not in request.args:
            return f'{arg} not provided', 400

    if all([
        request.args['hub.mode'] == source_channel.pubsubhubbub_mode,
        request.args['hub.verify_token'] == source_channel.verify_token
    ]):
        source_channel.pubsubhubbub_expires_at = datetime.now() + timedelta(seconds=int(request.args['hub.lease_seconds']))
        db.session.add(source_channel)
        db.session.commit()
        return request.args['hub.challenge'], 200

    return '', 204


@hooks.route('/new/<string:channel_id>', methods=['POST'])
def push_notification(channel_id: str):
    """
    Docs: https://developers.google.com/youtube/v3/guides/push_notifications
    Hub: https://pubsubhubbub.appspot.com/subscribe
    Example:
        <feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
          <link rel="hub" href="https://pubsubhubbub.appspot.com"/>
          <link rel="self" href="https://www.youtube.com/xml/feeds/videos.xml?channel_id=CHANNEL_ID"/>
          <title>YouTube video feed</title>
          <updated>2015-04-01T19:05:24.552394234+00:00</updated>
          <entry>
            <id>yt:video:VIDEO_ID</id>
            <yt:videoId>VIDEO_ID</yt:videoId>
            <yt:channelId>CHANNEL_ID</yt:channelId>
            <title>Video title</title>
            <link rel="alternate" href="http://www.youtube.com/watch?v=VIDEO_ID"/>
            <author>
             <name>Channel title</name>
             <uri>http://www.youtube.com/channel/CHANNEL_ID</uri>
            </author>
            <published>2015-03-06T21:40:57+00:00</published>
            <updated>2015-03-09T19:05:24.552394234+00:00</updated>
          </entry>
        </feed>
    :return: 
    """
    hub_signature = request.headers.get('X-Hub-Signature')
    _data = request.data

    source = SourceChannel.query.filter_by(channel_id=channel_id).first_or_404()
    my_signature = generate_signature(_data, source.secret)

    if f'sha1={my_signature}' != hub_signature:
        # If signature test failed we must return 200 code, because our service handled this request correctly,
        # but we don't provide any data, and does not create entries in database
        return {}, 200

    data = parse(_data)

    if 'feed' not in data or 'entry' not in data['feed']:
        raise BadRequest('Invalid XML')

    yt_video = data['feed']['entry']
    entry = YoutubeVideo.from_xml(yt_video)

    if entry.channel.channel_id != channel_id:
        raise BadRequest('Channels does not match')

    db.session.add(entry)
    db.session.commit()

    download_task = dict(
        _type_='DownloadTask',
        url=entry.uri,
        channel_id=entry.channel.channel_id,
    )
    media_manager.send_task('media_manager.download', (download_task,))

    return entry.serialize(), 200
