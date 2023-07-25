import os
import unittest
import importlib
from ipaddress import IPv4Address
from unittest.mock import Mock, patch



class chassis_mock:
    State = 'ready'

class mock_session:
    State = 'ACTIVE'
    Id = 8020

class SessionMock:
    def __init__(self, *args, **kwargs):
        self.Ixnetwork = Mock()
        self.Ixnetwork._connection = Mock()
        self.Ixnetwork._connection._session = Mock()
        self.Ixnetwork._connection._read = Mock(return_value={
            'links': [
                {'rel': 'self', 'method': 'GET', 'href': '/api/v1/sessions/8020/ixnetwork/globals'}, 
                {'rel': 'meta', 'method': 'OPTIONS', 'href': '/api/v1/sessions/8020/ixnetwork/globals'}
	        ]
        })
        self.Ixnetwork.AvailableHardware = Mock()
        self.Ixnetwork.AvailableHardware.Chassis = Mock()
        self.Ixnetwork.AvailableHardware.Chassis.add = Mock(return_value=chassis_mock)
        self.Ixnetwork.AvailableHardware.Chassis.find = Mock(return_value=chassis_mock)
        self.Session = Mock()

        self.Session.find = Mock(return_value=[mock_session])

    def __call__(self, *args, **kwargs):
        self.called_args = args, kwargs
        return self


session_mock = SessionMock()

class TestIxiaIxNetworkRestPy(unittest.TestCase):

    @patch('ixnetwork_restpy.SessionAssistant', new=session_mock)
    def test_connect(self):
        # force module reload so the mock can catch the SessionAssistant class
        from pyats.topology import loader
        from genie.trafficgen.ixiarestpy.implementation import IxiaRestPy
        import genie.trafficgen
        importlib.reload(genie.trafficgen.ixiarestpy.implementation)

        tb_file = os.path.join(os.path.dirname(__file__), 'testbed.yaml')
        tb = loader.load(tb_file)
        dev = tb.devices.ixia4
        dev.instantiate()
        self.assertTrue(isinstance(dev.default, IxiaRestPy))
        self.assertEqual(dev.default.via, 'tgn')
        
        dev.connect()
        called_args = session_mock.called_args[1]
        called_args.update(SessionName=None)
        self.assertEqual(called_args,
                         dict(IpAddress='192.0.0.1',
                              RestPort=11009,
                              UserName='test',
                              Password='test',
                              SessionName=None,
                              SessionId=None,
                              ApiKey=None,
                              ClearConfig=False,
                              LogLevel='info',
                              LogFilename='restpy.log')
        )
