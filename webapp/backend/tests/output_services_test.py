import pytest

from flask_migrate import init, migrate, upgrade

from app import create_app, db
from app.celery import celery as _celery
from app.models.output_services import OutputService, TelegramOutputService
from app.models.source_channels import SourceChannel, SourceChannelOutputService


@pytest.fixture(scope='module')
def celery(request):
    _celery.conf.update(broker_url='memory://localhost/', task_always_eager=True)
    return _celery


@pytest.fixture()
def app(tmpdir):
    _tmpdir = str(tmpdir)
    db_connection = f'sqlite:///{_tmpdir}/test-db.sqlite'
    migrations_dir = f'{_tmpdir}/migrations'
    # migrations_dir = f'../migrations'

    app = create_app()
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': db_connection
    })

    # create new clear database for tests

    with app.app_context():
        init(migrations_dir)
        migrate(migrations_dir, 'init')
        upgrade(migrations_dir)

        # create data for tests
        output_service = TelegramOutputService(title='test telegram channel',
                                               channel_id=-1000000000000,
                                               )
        channel_subscribe = SourceChannel(title='test subscribe',
                                          channel_id='pytest_channel_sub_id',
                                          pubsubhubbub_mode='subscribe',
                                          )
        source_output = SourceChannelOutputService(output_service=output_service,
                                                   source_channel=channel_subscribe,
                                                   )
        db.session.add_all([channel_subscribe, output_service, source_output])
        db.session.commit()

    # other setup can go here

    yield app

    # clean up / reset resources here


@pytest.fixture()
def client(app, celery):
    return app.test_client()


@pytest.mark.parametrize("filter, expected_length", [('%', 1),
                                                     ('%telegram%', 1),
                                                     ('notfound', 0),
                                                     ])
def test_find(client, filter, expected_length):
    resp = client.get('/outputs/find', query_string={
        'filter_by_title__ilike': filter,
    })
    assert resp.status_code == 200
    assert resp.json['status'] == 'success'
    assert resp.json['data']['pagination']['page'] == 1
    assert len(resp.json['data']['items']) == expected_length


@pytest.mark.parametrize("_id, expected_title", [(1, 'test telegram channel'),
                                                 ])
def test_get(client, _id, expected_title):
    resp = client.get(f'/outputs/{_id}', query_string={
        'include_sources': 'yes',
    })
    assert resp.status_code == 200
    assert resp.json['status'] == 'success'
    assert resp.json['data']['id'] == _id
    assert resp.json['data']['title'] == expected_title
    assert len(resp.json['data']['sources']) == 1


def test_get_notfound(client):
    resp = client.get(f'/outputs/100')
    assert resp.status_code == 404
    assert resp.json['status'] == 'error'


def test_post(client):
    resp = client.post('/outputs/', json=dict(
        title='test channel',
        type='telegram',
        channel_id=-1000000000001,
        sources=[1],
    ))
    assert resp.status_code == 200
    assert resp.json['status'] == 'success'
    assert resp.json['data']['title'] == 'test channel'
    assert resp.json['data']['channel_id'] == -1000000000001


def test_post_error(client):
    resp = client.post('/outputs/', json=dict(
        title='test channel',
        channel_id=-1000000000001,
    ))
    assert resp.status_code == 400
    assert resp.json['status'] == 'error'
    assert resp.json['message'] == '400 Bad Request: Missing required property `type`'


def test_put(client):
    resp = client.put('/outputs/1', json=dict(
        title='test put',
        type='telegram',
        sources=[],
    ), query_string={
        'include_sources': 'yes',
    })
    assert resp.status_code == 200
    assert resp.json['status'] == 'success'
    assert resp.json['data']['title'] == 'test put'
    assert resp.json['data']['channel_id'] == -1000000000000
    assert len(resp.json['data']['sources']) == 0


def test_put_error(client):
    resp = client.put('/outputs/100', json=dict(
        title='test put error',
    ))
    assert resp.status_code == 400
    assert resp.json['status'] == 'error'


def test_delete(client):
    resp = client.delete('/outputs/1')
    assert resp.status_code == 200
    assert resp.json['status'] == 'success'


def test_delete_error(client):
    resp = client.delete('/outputs/100')
    assert resp.status_code == 404
    assert resp.json['status'] == 'error'

