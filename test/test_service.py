"""
Test functions in brewblox_service.service.py
"""

from asyncio import CancelledError
from unittest.mock import call

import pytest
from aiohttp import web_exceptions
from aiohttp.client_exceptions import ServerDisconnectedError

from brewblox_service import features, service, testing

TESTED = service.__name__


class DummyFeature(features.ServiceFeature):
    async def startup(self, app):
        pass

    async def shutdown(self, app):
        pass


@pytest.fixture
def app(app, mocker):
    app.router.add_static(prefix='/static', path='/usr')
    features.add(app, DummyFeature(app))
    service.furnish(app)
    return app


def test_parse_args():
    # test defaults
    parser = service.create_parser('brewblox')
    args = parser.parse_args([])
    assert args.port == 5000
    assert not args.debug
    assert args.host == '0.0.0.0'
    assert args.name == 'brewblox'

    # test host
    args = parser.parse_args(['-H', 'host_name'])
    assert args.host == 'host_name'

    # test name
    args = parser.parse_args(['-n', 'service_name'])
    assert args.name == 'service_name'

    # test port
    args = parser.parse_args(['-p', '1234'])
    assert args.port == 1234

    # test debug mode
    args = parser.parse_args(['--debug'])
    assert args.debug


def test_init_logging(mocker):
    log_mock = mocker.patch(TESTED + '.logging')

    args = service.create_parser('brewblox').parse_args([])
    service._init_logging(args)

    assert log_mock.basicConfig.call_count == 1

    log_mock.getLogger.assert_has_calls([
        call('aiohttp.access'),
        call().setLevel(log_mock.WARN),
    ])


def test_no_logging_mute(mocker):
    log_mock = mocker.patch(TESTED + '.logging')

    args = service.create_parser('brewblox').parse_args(['--debug'])
    service._init_logging(args)

    assert log_mock.getLogger.call_count == 0


def test_create_app(sys_args, app_config, mocker):
    raw_args = sys_args[1:] + ['--unknown', 'really']
    m_error = mocker.patch(TESTED + '.LOGGER.error')
    app = service.create_app(default_name='brewblox', raw_args=raw_args)

    assert app is not None
    assert app['config'] == app_config
    m_error.assert_called_once_with(testing.matching(r".*\['--unknown', 'really'\]"))


def test_create_no_args(sys_args, app_config, mocker):
    mocker.patch(TESTED + '.sys.argv', sys_args)

    with pytest.raises(AssertionError):
        service.create_app()

    app = service.create_app(default_name='default')

    assert app['config'] == app_config


def test_create_w_parser(sys_args, app_config, mocker):
    parser = service.create_parser('brewblox')
    parser.add_argument('-t', '--test', action='store_true')

    sys_args += ['-t']
    app = service.create_app(parser=parser, raw_args=sys_args[1:])
    assert app['config']['test'] is True


async def test_furnish(app, client):
    res = await client.get('/test_app/_service/status')
    assert res.status == 200
    assert 'Access-Control-Allow-Origin' in res.headers
    assert await res.json() == {'status': 'ok'}

    # CORS preflight
    res = await client.options('/test_app/_service/status')
    assert res.status == 200
    assert 'Access-Control-Allow-Origin' in res.headers


async def test_error_cors(app, client, mocker):
    res = await client.get('/test_app/nonsense')
    assert res.status == 404
    assert 'Access-Control-Allow-Origin' in res.headers

    mocker.patch(TESTED + '.web.json_response').side_effect = RuntimeError
    res = await client.get('/test_app/_service/status')
    assert res.status == 500
    assert 'Access-Control-Allow-Origin' in res.headers

    mocker.patch(TESTED + '.web.json_response').return_value = web_exceptions.HTTPUnauthorized(reason='')
    res = await client.get('/test_app/_service/status')
    assert res.status == 401
    assert 'Access-Control-Allow-Origin' in res.headers

    mocker.patch(TESTED + '.web.json_response').side_effect = web_exceptions.HTTPUnauthorized(reason='')
    res = await client.get('/test_app/_service/status')
    assert res.status == 401
    assert 'Access-Control-Allow-Origin' in res.headers

    mocker.patch(TESTED + '.web.json_response').side_effect = CancelledError
    with pytest.raises(ServerDisconnectedError):
        await client.get('/test_app/_service/status')


def test_run(app, mocker):
    run_mock = mocker.patch(TESTED + '.web.run_app')

    service.run(app)
    run_mock.assert_called_with(app, host='0.0.0.0', port=1234)

    service.run(app, False)
    run_mock.assert_called_with(app, path=testing.matching(r'/tmp/.+/dummy.sock'))
