'''
Connection Implementation class for Ixia traffic generator using
ixnetwork Python package to interact with Ixia device:
https://pypi.org/project/ixnetwork/

Requirements:
    * IxOS/IxVM 7.40 or higher
    * IxNetork EA version 7.40 or higher
'''

# Python
import re
import os
import csv
import time
import logging
from prettytable import PrettyTable, from_csv

# pyATS
from ats.easypy import runtime
from ats.log.utils import banner
from ats.connections import BaseConnection

# Genie
from genie.utils.timeout import Timeout
from genie.utils.summary import Summary
from genie.harness.utils import get_url
from genie.trafficgen.trafficgen import TrafficGen
from genie.harness.exceptions import GenieTgnError

# IxNetwork Native
try:
    from IxNetwork import IxNet
except ImportError as e:
    raise ImportError("IxNetwork package is not installed in virtual env - "
                      "https://pypi.org/project/IxNetwork/") from e

# Logger
log = logging.getLogger(__name__)

# ixNet pass
_PASS = '::ixNet::OK'


class IxiaNative(TrafficGen):

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # Init class variables
        self.ixNet = IxNet()
        self._is_connected = False
        self.virtual_ports = []
        self._genie_view = None
        self._genie_page = None
        self._golden_profile = PrettyTable()
        # Valid QuickTests (to be expanded as tests have been validated)
        self.valid_quicktests = ['rfc2544frameLoss',
                                 'rfc2544throughput',
                                 'rfc2544back2back',
                                 ]

        # Get Ixia device arguments from testbed YAML file
        for key in ['ixnetwork_api_server_ip', 'ixnetwork_tcl_port',
                    'ixia_port_list', 'ixnetwork_version', 'ixia_chassis_ip',
                    'ixia_license_server_ip']:
            # Verify Ixia ports provided are a list
            if key is 'ixia_port_list':
                if not isinstance(self.connection_info[key], list):
                    log.error("Attribute '{}' is not a list as expected".\
                              format(key))
            try:
                setattr(self, key, self.connection_info[key])
            except Exception:
                raise GenieTgnError("Argument '{k}' is not found in testbed "
                                    "YAML for device '{d}'".\
                                    format(k=key, d=self.device.name))

        # Ixia Chassis Details
        header = "Ixia Chassis Details"
        summary = Summary(title=header, width=45)
        summary.add_message(msg='IxNetwork API Server: {}'.\
                            format(self.ixnetwork_api_server_ip))
        summary.add_sep_line()
        summary.add_message(msg='IxNetwork API Server Platform: Windows')
        summary.add_sep_line()
        summary.add_message(msg='IxNetwork Version: {}'.\
                         format(self.ixnetwork_version))
        summary.add_sep_line()
        summary.add_message(msg='Ixia Chassis: {}'.\
                         format(self.ixia_chassis_ip))
        summary.add_sep_line()
        summary.add_message(msg='Ixia License Server: {}'.\
                         format(self.ixia_license_server_ip))
        summary.add_sep_line()
        summary.add_message(msg='Ixnetwork TCL Port: {}'.\
                         format(self.ixnetwork_tcl_port))
        summary.add_sep_line()
        summary.print()

        # Genie Traffic Documentation
        url = get_url().replace("genie", "genietrafficgen")
        log.info('For more information, see Genie traffic documentation: '
                 '{}/ixianative.html'.format(url))


    def isconnected(func):
        '''Decorator to make sure session to device is active

           There is limitation on the amount of time the session can be active
           to IxNetwork API server. However, there are no way to verify if the
           session is still active unless we test sending a command.
         '''
        def decorated(self, *args, **kwargs):
            # Check if connected
            try:
                log.propagate = False
                self.ixNet.getAttribute('/globals', '-buildNumber')
            except Exception:
                self.connect()
            finally:
                log.propagate = True
            return func(self, *args, **kwargs)
        return decorated


    @BaseConnection.locked
    def connect(self):
        '''Connect to Ixia'''

        log.info(banner("Connecting to IXIA"))

        # Execute connect on IxNetwork
        try:
            connect = self.ixNet.connect(self.ixnetwork_api_server_ip,
                                        '-port', self.ixnetwork_tcl_port,
                                        '-version', self.ixnetwork_version,
                                        '-setAttribute', 'strict')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Failed to connect to device '{d}' on port "
                                "'{p}'".format(d=self.device.name,
                                            p=self.ixnetwork_tcl_port)) from e
        # Verify return
        try:
            assert connect == _PASS
        except AssertionError as e:
            log.error(connect)
            raise GenieTgnError("Failed to connect to device '{d}' on port "
                                "'{p}'".format(d=self.device.name,
                                            p=self.ixnetwork_tcl_port)) from e
        else:
            self._is_connected = True
            log.info("Connected to IxNetwork API server on TCL port '{p}'".\
                     format(d=self.device.name, p=self.ixnetwork_tcl_port))


    @BaseConnection.locked
    def disconnect(self):
        '''Disconnect from traffic generator device'''

        # Execute disconnect on IxNetwork
        try:
            disconnect = self.ixNet.disconnect()
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to disconnect from '{}".\
                                format(self.device.name))

        # Verify return
        try:
            assert disconnect == _PASS
        except AssertionError as e:
            log.error(disconnect)
            raise GenieTgnError("Unable to disconnect from '{}'".\
                                format(self.device.name))
        else:
            self._is_connected = False
            log.info("Disconnected from IxNetwork API server on TCL port '{p}'".\
                     format(d=self.device.name, p=self.ixnetwork_tcl_port))


    @BaseConnection.locked
    @isconnected
    def load_configuration(self, configuration, wait_time=60):
        '''Load static configuration file onto Ixia'''

        log.info(banner("Loading configuration"))

        # Ixia Configuration Details
        header = "Ixia Configuration Information"
        summary = Summary(title=header, width=105)
        summary.add_message(msg='Ixia Ports: {}'.format(self.ixia_port_list))
        summary.add_sep_line()
        summary.add_message(msg='File: {}'.format(configuration))
        summary.add_sep_line()
        summary.print()

        # Execute load config on IxNetwork
        try:
            load_config = self.ixNet.execute('loadConfig', 
                                             self.ixNet.readFrom(configuration))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to load configuration file '{f}' onto "
                                "device '{d}'".format(d=self.device.name,
                                                f=configuration)) from e
        # Verify return
        try:
            assert load_config == _PASS
        except AssertionError as e:
            log.error(load_config)
            raise GenieTgnError("Unable to load configuration file '{f}' onto "
                                "device '{d}'".format(d=self.device.name,
                                                f=configuration)) from e
        else:
            log.info("Loaded configuration file '{f}' onto device '{d}'".\
                    format(f=configuration, d=self.device.name))

        # Wait after loading configuration file
        log.info("Waiting for '{}' seconds after loading configuration...".\
                 format(wait_time))
        time.sleep(wait_time)

        # Verify traffic is in 'unapplied' state
        log.info("Verify traffic is in 'unapplied' state after loading configuration")
        try:
            assert self.get_traffic_attribute(attribute='state') == 'unapplied'
        except AssertionError as e:
            raise GenieTgnError("Traffic is not in 'unapplied' state after "
                                "loading configuration onto device '{}'".\
                                format(self.device.name)) from e
        else:
            log.info("Traffic in 'unapplied' state after loading configuration "
                     "onto device '{}'".format(self.device.name))


    @BaseConnection.locked
    @isconnected
    def start_all_protocols(self, wait_time=60):
        '''Start all protocols on Ixia'''

        log.info(banner("Starting routing engine"))

        # Start protocols on IxNetwork
        try:
            start_protocols = self.ixNet.execute('startAllProtocols')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to start all protocols on device '{}'".\
                                format(self.device.name)) from e
        # Verify return
        try:
            assert start_protocols == _PASS
        except AssertionError as e:
            log.error(start_protocols)
            raise GenieTgnError("Unable to start all protocols on device '{}'".\
                                format(self.device.name)) from e
        else:
            log.info("Started protocols on device '{}".format(self.device.name))

        # Wait after starting protocols
        log.info("Waiting for '{}' seconds after starting all protocols...".\
                    format(wait_time))
        time.sleep(wait_time)


    @BaseConnection.locked
    @isconnected
    def stop_all_protocols(self, wait_time=60):
        '''Stop all protocols on Ixia'''

        log.info(banner("Stopping routing engine"))

        # Stop protocols on IxNetwork
        try:
            stop_protocols = self.ixNet.execute('stopAllProtocols')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to stop all protocols on device '{}'".\
                                format(self.device.name)) from e
        # Verify return
        try:
            assert stop_protocols == _PASS
        except AssertionError as e:
            log.error(stop_protocols)
            raise GenieTgnError("Unable to stop all protocols on device '{}'".\
                                format(self.device.name)) from e
        else:
            log.info("Stopped protocols on device '{}'".format(self.device.name))

        # Wait after stopping protocols
        log.info("Waiting for  '{}' seconds after stopping all protocols...".\
                    format(wait_time))
        time.sleep(wait_time)


    @BaseConnection.locked
    @isconnected
    def apply_traffic(self, wait_time=60):
        '''Apply L2/L3 traffic on Ixia'''

        log.info(banner("Applying L2/L3 traffic"))

        # Apply traffic on IxNetwork
        try:
            apply_traffic = self.ixNet.execute('apply', '/traffic')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to apply L2/L3 traffic on device '{}'".\
                                format(self.device.name)) from e
        # Verify return
        try:
            assert apply_traffic == _PASS
        except AssertionError as e:
            log.error(apply_traffic)
            raise GenieTgnError("Unable to apply L2/L3 traffic on device '{}'".\
                                format(self.device.name)) from e
        else:
            log.info("Applied L2/L3 traffic on device '{}'".format(self.device.name))

        # Wait after applying L2/L3 traffic
        log.info("Waiting for '{}' seconds after applying L2/L3 traffic...".\
                    format(wait_time))
        time.sleep(wait_time)

        # Verify traffic is in 'stopped' state
        log.info("Verify traffic is in 'stopped' state...")
        try:
            assert self.get_traffic_attribute(attribute='state') == 'stopped'
        except Exception as e:
            raise GenieTgnError("Traffic is not in 'stopped' state after "
                                "applying L2/L3 traffic on device '{}'".\
                                format(self.device.name))
        else:
            log.info("Traffic is in 'stopped' state after applying traffic as "
                     "expected")


    @BaseConnection.locked
    @isconnected
    def send_arp(self, wait_time=10):
        '''Send ARP to all interfaces from Ixia'''

        log.info(banner("Sending ARP to all interfaces from Ixia"))

        # Send ARP from Ixia
        try:
            send_arp = self.ixNet.execute('sendArpAll')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to send ARP to all interfaces on device"
                                " '{}'".format(self.device.name)) from e
        # Verify return
        try:
            assert send_arp == _PASS
        except AssertionError as e:
            log.error(send_arp)
            raise GenieTgnError("Unable to send ARP to all interfaces on device"
                                " '{}'".format(self.device.name)) from e
        else:
            log.info("Sent ARP to all interfaces on device '{}'".\
                    format(self.device.name))

        # Wait after sending ARP
        log.info("Waiting for '{}' seconds after sending ARP to all interfaces...".\
                    format(wait_time))
        time.sleep(wait_time)


    @BaseConnection.locked
    @isconnected
    def send_ns(self, wait_time=10):
        '''Send NS to all interfaces from Ixia'''

        log.info(banner("Sending NS to all interfaces from Ixia"))

        # Sent NS from Ixia
        try:
            send_ns = self.ixNet.execute('sendNsAll')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error sending NS to all interfaces on device "
                                "'{}'".format(self.device.name)) from e
        try:
            assert send_ns == _PASS
        except AssertionError as e:
            log.error(send_ns)
            raise GenieTgnError("Error sending NS to all interfaces on device "
                                "'{}'".format(self.device.name)) from e
        else:
            log.info("Sent NS to all interfaces on device '{}'".\
                        format(self.device.name))

        # Wait after sending NS
        log.info("Waiting for '{}' seconds after sending NS...".\
                    format(wait_time))
        time.sleep(wait_time)


    @BaseConnection.locked
    @isconnected
    def start_traffic(self, wait_time=60):
        '''Start traffic on Ixia'''

        log.info(banner("Starting L2/L3 traffic"))

        # Check if traffic is already started
        state = self.get_traffic_attribute(attribute='state')
        running = self.get_traffic_attribute(attribute='isTrafficRunning')
        if state == 'started' or running == 'true':
            log.info("Traffic is already running and in 'started' state")
            return

        # Start traffic on IxNetwork
        try:
            start_traffic = self.ixNet.execute('start', '/traffic')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to start traffic on device '{}'".\
                                format(self.device.name)) from e
        # Verify return
        try:
            assert start_traffic == _PASS
        except AssertionError as e:
            log.error(start_traffic)
            raise GenieTgnError("Unable to start traffic on device '{}'".\
                                format(self.device.name)) from e
        else:
            log.info("Started L2/L3 traffic on device '{}'".\
                        format(self.device.name))

        # Wait after starting L2/L3 traffic for streams to converge to steady state
        log.info("Waiting for '{}' seconds after after starting L2/L3 traffic "
                 "for streams to converge to steady state...".format(wait_time))
        time.sleep(wait_time)

        # Check if traffic is in 'started' state
        log.info("Checking if traffic is in 'started' state...")
        try:
            assert self.get_traffic_attribute(attribute='state') == 'started'
        except AssertionError as e:
            log.error(e)
            raise GenieTgnError("Traffic is not in 'started' state")
        else:
            log.info("Traffic is in 'started' state")


    @BaseConnection.locked
    @isconnected
    def stop_traffic(self, wait_time=60):
        '''Stop traffic on Ixia'''

        log.info(banner("Stopping L2/L3 traffic"))

        # Check if traffic is already stopped
        state = self.get_traffic_attribute(attribute='state')
        running = self.get_traffic_attribute(attribute='isTrafficRunning')
        if state == 'stopped' or running == 'false':
            log.info("Traffic is not running or already in 'stopped' state")
            return

        # Stop traffic on IxNetwork
        try:
            stop_traffic = self.ixNet.execute('stop', '/traffic')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to stop traffic on device '{}'".\
                                format(self.device.name)) from e
        # Verify result
        try:
            assert stop_traffic == _PASS
        except AssertionError as e:
            log.error(stop_traffic)
            raise GenieTgnError("Unable to stop traffic on device '{}'".\
                                format(self.device.name)) from e
        else:
            log.info("Stopped L2/L3 traffic on device '{}'".\
                        format(self.device.name))

        # Wait after starting L2/L3 traffic for streams to converge to steady state
        log.info("Waiting for '{}' seconds after after stopping L2/L3 "
                 "traffic...".format(wait_time))
        time.sleep(wait_time)

        # Check if traffic is in 'stopped' state
        log.info("Checking if traffic is in 'stopped' state...")
        try:
            assert self.get_traffic_attribute(attribute='state') == 'stopped'
        except AssertionError as e:
            log.error(e)
            raise GenieTgnError("Traffic is not in 'stopped' state")
        else:
            log.info("Traffic is in 'stopped' state")


    @BaseConnection.locked
    @isconnected
    def clear_statistics(self, wait_time=10):
        '''Clear all traffic, port, protocol statistics on Ixia'''

        log.info(banner("Clearing traffic statistics"))

        log.info("Clearing all statistics...")
        try:
            clear_stats = self.ixNet.execute('clearStats')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to clear traffic statistics") from e
        else:
            log.info("Successfully cleared traffic statistics on device '{}'".\
                         format(self.device.name))

        log.info("Clearing port statistics...")
        try:
            clear_port_stats = self.ixNet.execute('clearPortsAndTrafficStats')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to clear port statistics") from e
        else:
            log.info("Successfully cleared port statistics on device '{}'".\
                         format(self.device.name))

        log.info("Clearing protocol statistics...")
        try:
            clear_protocol_stats = self.ixNet.execute('clearProtocolStats')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to clear protocol statistics") from e
        else:
            log.info("Successfully cleared protocol statistics on device '{}'".\
                         format(self.device.name))

        # Wait after clearing statistics
        log.info("Waiting for '{}' seconds after clearing statistics".\
                    format(wait_time))
        time.sleep(wait_time)


    @BaseConnection.locked
    @isconnected
    def create_genie_statistics_view(self, view_create_interval=30, view_create_iteration=10, disable_tracking=False, disable_port_pair=False):
        '''Creates a custom TCL View named "Genie" with the required stats data'''

        log.info(banner("Creating new custom IxNetwork traffic statistics view 'GENIE'"))

        # Default statistics to add to custom 'GENIE' traffic statistics view
        default_stats_list = ["Frames Delta",
                              "Tx Frames",
                              "Rx Frames",
                              "Loss %",
                              "Tx Frame Rate",
                              "Rx Frame Rate",
                              ]

        # Delete any previously created TCL Views called "GENIE"
        log.info("Deleting any existing traffic statistics view 'GENIE'...")
        try:
            for view in self.ixNet.getList('/statistics', 'view'):
                if self.ixNet.getAttribute(view, '-caption') == 'GENIE':
                    self.ixNet.remove(view)
                    self.ixNet.commit()
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to delete any previously created "
                                "traffic statistics view named 'GENIE'.") from e

        # Enable 'Traffic Items' filter if not present
        if disable_tracking:
            log.info("Not enabling 'Traffic Items' filter for all traffic streams")
        else:
            self.enable_flow_tracking_filter(tracking_filter='trackingenabled0')

        # Enable 'Source/Dest Port Pair' filter if not present
        if disable_port_pair:
            log.info("Not enabling 'Source/Dest Port Pair' filter for all traffic streams")
        else:
            self.enable_flow_tracking_filter(tracking_filter='sourceDestPortPair0')

        # Create a new TCL View called "GENIE"
        log.info("Creating a new traffic statistics view 'GENIE'")
        try:
            self._genie_view = self.ixNet.add(self.ixNet.getRoot() + '/statistics', 'view')
            self.ixNet.setAttribute(self._genie_view, '-caption', 'GENIE')
            self.ixNet.setAttribute(self._genie_view, '-type', 'layer23TrafficFlow')
            self.ixNet.setAttribute(self._genie_view, '-visible', 'true')
            self.ixNet.commit()
            self._genie_view = self.ixNet.remapIds(self._genie_view)
            self._genie_view = self._genie_view[0]
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to create new traffic statistics view "
                                "named 'GENIE'.") from e

        # Populate traffic stream statistics in new TCL View 'GENIE'
        log.info("Populating custom IxNetwork traffic statistics view 'GENIE'...")
        try:
            # Get available traffic items, port filters
            avail_traffic_items = self.ixNet.getList(self._genie_view, 'availableTrafficItemFilter')
            avail_port_filter_list = self.ixNet.getList(self._genie_view, 'availablePortFilter')
            layer23_traffic_flow_filter = self.ixNet.getList(self._genie_view, 'layer23TrafficFlowFilter')

            # Set attributes
            self.ixNet.setAttribute(self._genie_view+'/layer23TrafficFlowFilter', '-trafficItemFilterIds', avail_traffic_items)
            self.ixNet.setAttribute(self._genie_view+'/layer23TrafficFlowFilter', '-portFilterIds', avail_port_filter_list)
            #self.ixNet.setAttribute(self._genie_view+'/layer23TrafficFlowFilter', '-egressLatencyBinDisplayOption', 'showIngressRows')

            # RemapIds
            self._genie_view = self.ixNet.remapIds(self._genie_view)[0]

            # Add specified columns to TCL view
            availableStatList = self.ixNet.getList(self._genie_view, 'statistic')
            for statName in default_stats_list:
                log.info("Adding '{}' statistics to 'GENIE' view".format(statName))
                stat = self._genie_view + '/statistic:' + '"{}"'.format(statName)
                if stat in availableStatList:
                    self.ixNet.setAttribute(stat, '-enabled', 'true')
                    self.ixNet.commit()
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to add Tx/Rx Frame Rate, Loss %, Frames"
                        " delta data to 'GENIE' traffic statistics view") from e

        # Create and set enumerationFilter to descending
        log.info("Get enumerationFilter to add custom columns to view")
        try:
            # Get enumerationFilter object
            enumerationFilter = self.ixNet.add(self._genie_view+'/layer23TrafficFlowFilter', 'enumerationFilter')
            self.ixNet.setAttribute(enumerationFilter, '-sortDirection', 'descending')
            self.ixNet.commit()
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get enumerationFilter object for"
                                " 'GENIE' view") from e

        # Adding 'Source/Dest Port Pair' column to 'GENIE' view
        log.info("Add 'Source/Dest Port Pair' column to 'GENIE' custom traffic statistics view...")
        try:
            # Find the 'Source/Dest Port Pair' object, add it to the 'GENIE' view
            source_dest_track_id = None
            trackingFilterIdList = self.ixNet.getList(self._genie_view, 'availableTrackingFilter')
            for track_id in trackingFilterIdList:
                if re.search('Source/Dest Port Pair', track_id):
                    source_dest_track_id = track_id
                    break
            if source_dest_track_id:
                self.ixNet.setAttribute(enumerationFilter, '-trackingFilterId', source_dest_track_id)
                self.ixNet.commit()
            else:
                raise GenieTgnError("Unable to add column for filter "
                                    "'Source/Dest Port Pair' to 'GENIE' "
                                    "traffic statistics view.")
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to add 'Source/Dest Port Pair' to "
                                "'GENIE' traffic statistics view.") from e

        # Enable 'GENIE' view visibility
        log.info("Enable custom IxNetwork traffic statistics view 'GENIE'...")
        try:
            # Re-enable TCL View "GENIE"
            self.ixNet.setAttribute(self._genie_view, '-enabled', 'true')
            self.ixNet.setAttribute(self._genie_view, '-visible', 'true')
            self.ixNet.commit()

            # Print to log
            log.info("Populated traffic statistics view 'GENIE' with required "
                     "data.")
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while enabling traffic statistics view "
                                "'GENIE' with required data.") from e

        # Create Genie Page object to parse later
        log.info("Displaying custom IxNetwork traffic statistics view 'GENIE' page...")
        try:
            # Get the page view of the TCL View "GENIE"
            self._genie_page = self.ixNet.getList(self._genie_view, 'page')[0]
            self.ixNet.setAttribute(self._genie_page, '-egressMode', 'conditional')
            self.ixNet.commit()

            # Poll until the view is ready
            for i in range(0, view_create_iteration):
                try:
                    assert self.ixNet.getAttribute(self._genie_page, '-isReady') == 'true'
                except Exception as e:
                    log.warning("IxNetwork traffic statistics view 'GENIE' is "
                                "not ready.\nSleeping {} seconds and before "
                                "checking traffic statistics view 'GENIE'".\
                                format(view_create_interval))
                    time.sleep(view_create_interval)
                else:
                    log.info("Custom IxNetwork traffic statistics view 'GENIE' "
                             "is ready.")
                    break
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to create custom IxNetwork traffic "
                                "statistics view 'GENIE' page.") from e


    @BaseConnection.locked
    @isconnected
    def check_traffic_loss(self, traffic_streams=[], max_outage=120, loss_tolerance=15, rate_tolerance=5, check_iteration=10, check_interval=60, outage_dict={}):
        '''Check traffic loss for each traffic stream configured on Ixia
            using statistics/data from 'Traffic Item Statistics' view'''

        # Verified streams to avoid duplicates
        verified_streams = []

        for i in range(check_iteration):

            log.info("\nAttempt #{}: Checking for traffic outage/loss".format(i+1))
            outage_check = True

            # Get and display 'GENIE' traffic statistics table containing outage/loss values
            traffic_table = self.create_traffic_streams_table()
            traffic_table_streams = self.get_traffic_items_from_genie_view(traffic_table=traffic_table)

            # Check all streams for traffic outage/loss
            for stream in traffic_table_streams:

                # Skip other streams if list of stream provided
                if traffic_streams and stream not in traffic_streams:
                    continue

                # Skip if duplicate (previously verified uni-direction stream with same name)
                if stream in verified_streams:
                    continue

                # Skip checks if traffic stream is not of type l2l3
                ti_type = self.get_traffic_stream_attribute(traffic_stream=stream,
                                                            attribute='trafficItemType')
                if ti_type != 'l2L3':
                    log.warning("SKIP: Traffic stream '{}' is not of type L2L3 "
                                "- skipping traffic loss checks".format(stream))
                    continue

                # Skip checks if traffic stream from "GENIE" table not in configuration
                if stream not in self.get_traffic_stream_names():
                    log.warning("SKIP: Traffic stream '{}' not found in current"
                                " configuration".format(stream))
                    continue

                # Determine outage values for this traffic stream
                if outage_dict and 'traffic_streams' in outage_dict and \
                    stream in outage_dict['traffic_streams']:
                    outage=outage_dict['traffic_streams'][stream]['max_outage']
                    loss=outage_dict['traffic_streams'][stream]['loss_tolerance']
                    rate=outage_dict['traffic_streams'][stream]['rate_tolerance']
                else:
                    outage=max_outage
                    loss=loss_tolerance
                    rate=rate_tolerance

                # Get source/dest port pair's associated with this traffic stream
                source_dest_pairs = []
                for row in traffic_table:
                    row.header = False ; row.border = False
                    if stream == row.get_string(fields=["Traffic Item"]).strip():
                        source_dest_pairs.append(row.get_string(fields=["Source/Dest Port Pair"]).strip())

                if not source_dest_pairs:
                    raise GenieTgnError("Unable to find source/dest port pairs "
                                        "associated with this traffic stream "
                                        "'{}'".format(stream))

                if len(source_dest_pairs) > 2:
                    raise GenieTgnError("Configuration mismatch - more than 2 "
                                        "source/dest port pairs found for "
                                        "traffic stream '{}'".format(stream))

                for pair in source_dest_pairs:
                    # Verify outage for traffic stream
                    if not self.verify_traffic_stream_outage(traffic_stream=stream,
                                                             source_dest_pair=pair,
                                                             traffic_table=traffic_table,
                                                             max_outage=outage,
                                                             loss_tolerance=loss,
                                                             rate_tolerance=rate):
                        # Traffic loss observed for stream
                        outage_check = False
                    # Add to list
                    verified_streams.append(stream)

            # Check if iteration required based on results
            if outage_check:
                log.info("\nSuccessfully verified traffic outages/loss is within "
                         "tolerance for given traffic streams")
                break
            elif i == check_iteration or i == check_iteration-1:
                # End of iterations, raise Exception and exit
                raise GenieTgnError("\nUnexpected traffic outage/loss is observed")
            else:
                # Traffic loss observed, sleep and recheck
                log.error("\nSleeping '{s}' seconds and rechecking traffic "
                          "streams for traffic outage/loss".\
                          format(s=check_interval))
                time.sleep(check_interval)


    @BaseConnection.locked
    @isconnected
    def verify_traffic_stream_outage(self, traffic_stream, source_dest_pair, traffic_table, max_outage=120, loss_tolerance=15, rate_tolerance=5):
        '''For each traffic stream configured on Ixia:
            * 1- Verify traffic outage (in seconds) is less than tolerance threshold
            * 2- Verify current loss % is less than tolerance threshold
            * 3- Verify difference between Tx Rate & Rx Rate is less than tolerance threshold
        '''

        log.info(banner("Checking traffic stream: '{s} | {t}'".format(s=source_dest_pair, t=traffic_stream)))

        # Init
        outage_check = False
        loss_check = False
        rate_check = False

        # Loop over all traffic items in configuration
        for row in traffic_table:

            # Get row in table associated with traffic stream
            row.header = False ; row.border = False
            # Get stream name and source dest/port pair
            current_stream = row.get_string(fields=["Traffic Item"]).strip()
            current_srcdest_pair = row.get_string(fields=["Source/Dest Port Pair"]).strip()
            if traffic_stream != current_stream or current_srcdest_pair != source_dest_pair:
                continue

            # 1- Verify traffic Outage (in seconds) is less than tolerance threshold
            log.info("1. Verify traffic outage (in seconds) is less than "
                     "tolerance threshold of '{}' seconds".format(max_outage))
            outage = row.get_string(fields=["Outage (seconds)"]).strip()
            if float(outage) <= float(max_outage):
                log.info("* Traffic outage of '{o}' seconds is within "
                         "expected maximum outage threshold of '{s}' seconds".\
                         format(o=outage, s=max_outage))
                outage_check = True
            else:
                log.error("* Traffic outage of '{o}' seconds is *NOT* within "
                          "expected maximum outage threshold of '{s}' seconds".\
                          format(o=outage, s=max_outage))

            # 2- Verify current loss % is less than tolerance threshold
            log.info("2. Verify current loss % is less than tolerance "
                     "threshold of '{}' %".format(loss_tolerance))
            if row.get_string(fields=["Loss %"]).strip() != '':
                loss_percentage = row.get_string(fields=["Loss %"]).strip()
            else:
                loss_percentage = 0

            # Check traffic loss
            if float(loss_percentage) <= float(loss_tolerance):
                log.info("* Current traffic loss of {l}% is within"
                         " maximum expected loss tolerance of {t}%".\
                         format(t=loss_tolerance, l=loss_percentage))
                loss_check = True
            else:
                log.error("* Current traffic loss of {l}% is *NOT* within"
                          " maximum expected loss tolerance of {t}%".\
                          format(t=loss_tolerance, l=loss_percentage))

            # 3- Verify difference between Tx Rate & Rx Rate is less than tolerance threshold
            log.info("3. Verify difference between Tx Rate & Rx Rate is less "
                     "than tolerance threshold of '{}' pps".format(rate_tolerance))
            tx_rate = row.get_string(fields=["Tx Frame Rate"]).strip()
            rx_rate = row.get_string(fields=["Rx Frame Rate"]).strip()
            if abs(float(tx_rate) - float(rx_rate)) <= float(rate_tolerance):
                log.info("* Difference between Tx Rate '{t}' and Rx Rate"
                         " '{r}' is within expected maximum rate loss"
                         " threshold of '{m}' packets per second".\
                         format(t=tx_rate, r=rx_rate, m=rate_tolerance))
                rate_check = True
            else:
                log.error("* Difference between Tx Rate '{t}' and Rx Rate"
                          " '{r}' is *NOT* within expected maximum rate loss"
                          " threshold of '{m}' packets per second".\
                          format(t=tx_rate, r=rx_rate, m=rate_tolerance))

            # Checks completed, avoid checking other streams with duplicate names
            break

        # If all streams had:
        #   1- No traffic outage beyond threshold
        #   2- No current loss beyond threshold
        #   3- No frames rate loss
        if outage_check and loss_check and rate_check:
            log.info("Traffic stream '{}': traffic outage, loss% and Tx/Rx Rate"
                     " difference within maximum expected threshold".\
                     format(traffic_stream))
            return True
        else:
            log.error("Traffic stream '{}': traffic outage, loss% and Tx/Rx Rate"
                      " difference *NOT* within maximum expected threshold".\
                      format(traffic_stream))
            return False


    @BaseConnection.locked
    @isconnected
    def create_traffic_streams_table(self, set_golden=False, clear_stats=False, clear_stats_time=30, view_create_interval=30, view_create_iteration=5):
        '''Returns traffic profile of configured streams on Ixia'''

        # Init
        traffic_table = PrettyTable()

        # If Genie view and page has not been created before, create one
        if not self._genie_view or not self._genie_page:
            self.create_genie_statistics_view(view_create_interval=view_create_interval,
                                              view_create_iteration=view_create_iteration)

        # Clear stats and wait
        if clear_stats:
            self.clear_statistics(wait_time=clear_stats_time)

        try:
            # Traffic table headers
            headers = self.ixNet.getAttribute(self._genie_page, '-columnCaptions')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get Column Captions from custom view 'GENIE'")

        # Add column for Outage
        headers.append('Outage (seconds)')
        # Arrange data to fit into table as required in final format:
        # ['Source/Dest Port Pair', 'Traffic Item', 'Tx Frames', 'Rx Frames', 'Frames Delta', 'Tx Frame Rate', 'Rx Frame Rate', 'Loss %', 'Outage (seconds)']
        del headers[0]
        headers[1], headers[0] = headers[0], headers[1]
        headers[5], headers[7] = headers[7], headers[5]
        headers[6], headers[5] = headers[5], headers[6]
        traffic_table.field_names = headers

        required_headers = ['Source/Dest Port Pair', 'Traffic Item',
                            'Tx Frames', 'Rx Frames', 'Frames Delta',
                            'Tx Frame Rate', 'Rx Frame Rate', 'Loss %',
                            'Outage (seconds)']
        # Check that all the expected headers were found
        for item in required_headers:
            try:
                assert item in headers
            except AssertionError as e:
                raise GenieTgnError("Column '{}' is missing from custom created 'GENIE' view".format(item))

        try:
            # Add rows with data
            for item in self.ixNet.getAttribute(self._genie_page, '-rowValues'):
                # Get row value data
                row_item = item[0]
                # Arrange data to fit into table as required in final format:
                # ['Source/Dest Port Pair', 'Traffic Item', 'Tx Frames', 'Rx Frames', 'Frames Delta', 'Tx Frame Rate', 'Rx Frame Rate', 'Loss %', 'Outage (seconds)']
                del row_item[0]
                row_item[1], row_item[0] = row_item[0], row_item[1]
                row_item[5], row_item[7] = row_item[7], row_item[5]
                row_item[6], row_item[5] = row_item[5], row_item[6]
                # Calculate outage in seconds from 'Frames Delta' and add to row
                frames_delta = row_item[4]
                tx_frame_rate = row_item[5]
                if tx_frame_rate == '0.000' or tx_frame_rate == '0':
                    outage_seconds = 0.0
                else:
                    outage_seconds = round(float(frames_delta)/float(tx_frame_rate), 3)
                row_item.append(str(outage_seconds))
                # Add data to traffic_table
                traffic_table.add_row(row_item)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get data from custom view 'GENIE'")

        # Align and print profile table in the logs
        traffic_table.align = "l"
        log.info(traffic_table)

        # If flag set, reset the golden profile
        if set_golden:
            log.info("\nSetting golden traffic profile\n")
            self._golden_profile = traffic_table

        # Return profile table to caller
        return traffic_table


    @BaseConnection.locked
    @isconnected
    def compare_traffic_profile(self, profile1, profile2, loss_tolerance=5, rate_tolerance=2):
        '''Compare two Ixia traffic profiles'''

        log.info(banner("Comparing traffic profiles"))

        # Check profile1
        if not isinstance(profile1, prettytable.PrettyTable) or not profile1.field_names:
            raise GenieTgnError("Profile1 is not in expected format or missing data")
        else:
            log.info("Profile1 is in expected format with data")

        # Check profile2
        if not isinstance(profile2, prettytable.PrettyTable) or not profile2.field_names:
            raise GenieTgnError("Profile2 is not in expected format or missing data")
        else:
            log.info("Profile2 is in expected format with data")

        # Compare both profiles

        # Check number of traffic items provided are the same
        profile1_ti = 0 ; profile2_ti = 0
        for row in profile1:
            if row.get_string(fields=['Traffic Item']):
                profile1_ti += 1
        for row in profile2:
            if row.get_string(fields=['Traffic Item']):
                profile2_ti += 1
        if profile2_ti != profile1_ti:
            raise GenieTgnError("Profiles do not have the same traffic items")

        # Traffic profile column headers
        # ['Source/Dest Port Pair', 'Traffic Item', 'Tx Frames', 'Rx Frames', 'Frames Delta', 'Tx Frame Rate', 'Rx Frame Rate', 'Loss %', 'Outage (seconds)']
        names = ['src_dest_pair', 'traffic_item', 'tx_frames', 'rx_frames', 'frames_delta', 'tx_rate', 'rx_rate', 'loss', 'outage']

        # Begin comparison between profiles
        compare_profile_failed = False
        for profile1_row, profile2_row in zip(profile1, profile2):
            profile1_row.header = False ; profile2_row.header = False
            profile1_row_values = {} ; profile2_row_values = {}
            for item, name in zip(profile1_row._rows[0], names):
                profile1_row_values[name] = item
            for item, name in zip(profile2_row._rows[0], names):
                profile2_row_values[name] = item

            # Ensure profiles have traffic data/content
            if profile1_row_values and profile2_row_values:
                # Compare traffic profiles
                if profile1_row_values['src_dest_pair'] == profile2_row_values['src_dest_pair'] and\
                    profile1_row_values['traffic_item'] == profile2_row_values['traffic_item']:

                    # Begin comparison
                    log.info(banner("Comparing profiles for traffic item '{}'".format(profile1_row_values['traffic_item'])))

                    # Compare Tx Frames Rate between two profiles
                    try:
                        assert abs(float(profile1_row_values['tx_rate']) - float(profile2_row_values['tx_rate'])) <= float(rate_tolerance)
                    except AssertionError as e:
                        compare_profile_failed = True
                        log.error("* Tx Frames Rate for profile 1 '{p1}' and "
                                  "profile 2 '{p2}' is more than expected "
                                  "tolerance of '{t}'".\
                                  format(p1=profile1_row_values['tx_rate'],
                                         p2=profile2_row_values['tx_rate'],
                                         t=rate_tolerance))
                    else:
                        log.info("* Tx Frames Rate difference between "
                                 "profiles is less than threshold of '{}'".\
                                 format(rate_tolerance))

                    # Compare Rx Frames Rate between two profiles
                    try:
                        assert abs(float(profile1_row_values['rx_rate']) - float(profile2_row_values['rx_rate'])) <= float(rate_tolerance)
                    except AssertionError as e:
                        compare_profile_failed = True
                        log.error("* Rx Frames Rate for profile 1 '{p1}' and"
                                  " profile 2 '{p2}' is more than expected "
                                  "tolerance of '{t}'".\
                                  format(p1=profile1_row_values['rx_rate'],
                                         p2=profile2_row_values['rx_rate'],
                                         t=rate_tolerance))
                    else:
                        log.info("* Rx Frames Rate difference between "
                                 "profiles is less than threshold of '{}'".\
                                 format(rate_tolerance))

                    # Check if loss % in profile1 is not ''
                    try:
                        float(profile1_row_values['loss'])
                    except ValueError:
                        profile1_row_values['loss'] = 0
                    # Check if loss % in profile2 is not ''
                    try:
                        float(profile2_row_values['loss'])
                    except ValueError:
                        profile2_row_values['loss'] = 0
                    # Compare Loss % between two profiles
                    try:
                        assert abs(float(profile1_row_values['loss']) - float(profile2_row_values['loss'])) <= float(loss_tolerance)
                    except AssertionError as e:
                        compare_profile_failed = True
                        log.error("* Loss % for profile 1 '{p1}' and "
                                  "profile 2 '{p2}' is more than expected "
                                  "tolerance of '{t}'".\
                                  format(p1=profile1_row_values['loss'],
                                         p2=profile2_row_values['loss'],
                                         t=loss_tolerance))
                    else:
                        log.info("* Loss % difference between profiles "
                                 "is less than threshold of '{}'".\
                                 format(loss_tolerance))
                else:
                    log.error("WARNING: The source/dest port pair and traffic"
                              " item are mismatched - skipping check")
            else:
                raise GenieTgnError("Profiles provided for comparison do not "
                                    "contain relevant traffic data")
        # Final result of comparison
        if compare_profile_failed:
            raise GenieTgnError("Comparison failed for traffic items between profiles")
        else:
            log.info("Comparison passed for all traffic items between profiles")


    #--------------------------------------------------------------------------#
    #                               Traffic                                    #
    #--------------------------------------------------------------------------#

    @BaseConnection.locked
    @isconnected
    def get_traffic_attribute(self, attribute):
        '''Returns the specified attribute for the given traffic configuration'''

        # Sample attributes
        # ['state', 'isApplicationTrafficRunning', 'isTrafficRunning']

        try:
            return self.ixNet.getAttribute('/traffic', '-{}'.format(attribute))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to check attribute '{}'".\
                                format(attribute)) from e


    @BaseConnection.locked
    @isconnected
    def get_traffic_items_from_genie_view(self, traffic_table):
        '''Returns list of all traffic items from within the "GENIE" view traffic table'''

        # Init
        traffic_streams = []

        # Loop over traffic table provided
        for row in traffic_table:
            row.header = False
            row.border = False
            traffic_streams.append(row.get_string(fields=["Traffic Item"]).strip())

        # Return to caller
        return traffic_streams


    @BaseConnection.locked
    @isconnected
    def enable_flow_tracking_filter(self, tracking_filter):
        '''Enable specific flow tracking filters for traffic streams'''

        # Check valid tracking_filter passed in
        assert tracking_filter in ['trackingenabled0',
                                   'sourceDestPortPair0',
                                   'sourceDestValuePair0',
                                   ]

        # Init
        filter_added = False

        # Mapping for filter names
        map_dict = {
            'trackingenabled0': "'Traffic Items'",
            'sourceDestPortPair0': "'Source/Dest Port Pair'",
            'sourceDestValuePair0': "'Source/Dest Value Pair"
            }

        log.info("Checking if {} filter present in L2L3 traffic streams...".\
                 format(map_dict[tracking_filter]))

        # Get all traffic stream objects in configuration
        traffic_streams = self.get_traffic_stream_objects()

        if not traffic_streams:
            raise GenieTgnError("Unable to find traffic streams for configuration")

        # Initial state
        initial_state = self.get_traffic_attribute(attribute='state')

        for ti in traffic_streams:

            # Get traffic stream type
            ti_type = None ; ti_name = None
            try:
                ti_type = self.ixNet.getAttribute(ti, '-trafficItemType')
                ti_name = self.ixNet.getAttribute(ti, '-name')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Unable to get traffic item '{}'"
                                    " attributes".format(ti))

            # If traffic streams is not of type 'l2l3' then skip to next stream
            if ti_type != 'l2L3':
                continue

            # Get the status of 'trackingenabled' filter
            trackByList = []
            try:
                trackByList = self.ixNet.getAttribute(ti + '/tracking', '-trackBy')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while checking status of filter '{f}'"
                                    " for traffic stream '{t}'".format(t=ti_name,
                                    f=tracking_filter))

            # If tracking_filter is already present then skip to next stream
            if tracking_filter in trackByList:
                continue

            # At this point, tracking_filter is not found, add it manually
            # Stop the traffic
            state = self.get_traffic_attribute(attribute='state')
            if state != 'stopped' and state != 'unapplied':
                self.stop_traffic(wait_time=15)

            log.info("Adding '{f}' filter to traffic stream '{t}'".\
                     format(f=tracking_filter, t=ti_name))

            # Add tracking_filter
            trackByList.append(tracking_filter)
            try:
                self.ixNet.setMultiAttribute(ti + '/tracking', '-trackBy', trackByList)
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while adding '{f}' filter to traffic"
                                    " stream '{t}'".format(t=ti_name,
                                    f=tracking_filter))
            else:
                filter_added = True

        # Loop exhausted, if tracking_filter added, commit+apply+start traffic
        if filter_added:
            self.ixNet.commit()
            self.apply_traffic(wait_time=15)
            if initial_state == 'started':
                self.start_traffic(wait_time=15)
        else:
            log.info("Filter '{}' previously configured for all L2L3 traffic "
                     "streams".format(tracking_filter))


    @BaseConnection.locked
    @isconnected
    def get_golden_profile(self):
        ''' Returns golden profile'''
        return self._golden_profile


    #--------------------------------------------------------------------------#
    #                           Virtual Ports                                  #
    #--------------------------------------------------------------------------#

    @BaseConnection.locked
    @isconnected
    def assign_ixia_ports(self, wait_time=15):
        '''Assign physical Ixia ports from the loaded configuration to the corresponding virtual ports'''

        log.info(banner("Assigning Ixia ports"))

        # Get list of physical ports
        log.info("Getting a list of physical ports...")
        self.physical_ports = []
        for item in self.ixia_port_list:
            log.info("-> {}".format(item))
            ixnet_port = []
            lc, port = item.split('/')
            for tmpvar in self.ixia_chassis_ip, lc, port:
                ixnet_port.append(tmpvar)
            self.physical_ports.append(ixnet_port)

        # Add the chassis
        log.info("Adding chassis...")
        try:
            self.chassis = self.ixNet.add(self.ixNet.getRoot() + \
                                          'availableHardware',\
                                          'chassis', '-hostname',\
                                          self.ixia_chassis_ip)
            self.ixNet.commit()
            self.chassis = self.ixNet.remapIds(self.chassis)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while adding chassis '{}'".\
                                format(self.ixia_chassis_ip))
        else:
            log.info("Successfully added chassis '{}'".\
                     format(self.ixia_chassis_ip))

        # Get virtual ports
        log.info("Getting virtual ports...")
        try:
            self.virtual_ports = self.ixNet.getList(self.ixNet.getRoot(), 'vport')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while getting virtual ports from "
                                "the loaded configuration")
        else:
            log.info("Found virtual ports from loaded configuration:")
            for item in self.virtual_ports:
                log.info("-> {}".format(item))

        # Assign ports
        log.info("Assign physical ports to virtual ports...")
        try:
            self.ixNet.execute('assignPorts', self.physical_ports, [],
                               self.virtual_ports, True)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to assign physical ports to virtual ports")
        else:
            log.info("Successfully assigned physical ports to virtual ports")
            log.info("Waiting {} seconds after assigning ports...".format(wait_time))
            time.sleep(wait_time)

        # Verify ports are up and connected
        log.info("Verify ports are up and connected...")
        for vport in self.virtual_ports:
            # Get the name
            try:
                name = self.ixNet.getAttribute(vport, '-name')
            except Exception as e:
                raise GenieTgnError("Unable to get 'name' for virtual port"
                                    " '{}'".format(vport))
            # Verify port is up
            try:
                state = self.ixNet.getAttribute(vport, '-state')
                assert state == 'up'
            except AssertionError as e:
                log.warning("Port '{}' is not 'up', sending ARP and rechecking state...")
                # Send ARP on port
                try:
                    self.send_arp(wait_time=wait_time)
                except GenieTgnError as e:
                    log.error(e)
                    raise GenieTgnError("Port '{n}' is '{s}' and not 'up' after"
                                        " sending ARP".format(n=name, s=state))
            else:
                log.info("Port '{}' is up as expected".format(name))

            # Verify port is connected
            try:
                assert self.ixNet.getAttribute(vport, '-isConnected') == 'true'
            except AssertionError as e:
                raise GenieTgnError("Port '{}' is not connected".format(name))
            else:
                log.info("Port '{}' is connected".format(name))

        # If all pass
        log.info("Assigned the following physical Ixia ports to virtual ports:")
        for port in self.ixia_port_list:
            log.info("-> Ixia Port: '{}'".format(port))


    @BaseConnection.locked
    @isconnected
    def set_ixia_virtual_ports(self):
        '''Set virtual Ixia ports for this configuration'''

        try:
            # Set virtual Ixia ports
            self.virtual_ports = self.ixNet.getList(self.ixNet.getRoot(), 'vport')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get virtual ports on Ixia")


    @BaseConnection.locked
    @isconnected
    def get_ixia_virtual_port(self, port_name):
        '''Return virtual Ixia port object from port_name'''

        # Set virtual Ixia ports if not previously set
        if not self.virtual_ports:
            self.set_ixia_virtual_ports()

        # Get vport object from port_name
        for item in self.virtual_ports:
            if port_name == self.get_ixia_virtual_port_attribute(item, 'name'):
                return item


    @BaseConnection.locked
    @isconnected
    def get_ixia_virtual_port_attribute(self, vport, attribute):
        '''Get attibute for virtual Ixia port'''

        try:
            # Extract Ixia virtual port settings/attribute
            value = self.ixNet.getAttribute(vport, '-{}'.format(attribute))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get attribute '{a}'' for ixia"
                                " port '{p}'".format(a=attribute, p=vport))
        else:
            return value


    #--------------------------------------------------------------------------#
    #                           Packet Capture                                 #
    #--------------------------------------------------------------------------#

    @BaseConnection.locked
    @isconnected
    def get_ixia_virtual_port_capture(self, port_name):

        # Get virtual Ixia port object
        try:
            vportObj = self.get_ixia_virtual_port(port_name=port_name)
        except:
            raise GenieTgnError("Unable to get virtual Ixia port object for "
                                "port '{}'".format(port_name))

        # Get captureObj for this virtual port
        try:
            return self.ixNet.getList(vportObj, 'capture')[0]
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get captureObj for port '{}'".\
                                format(port_name))


    @BaseConnection.locked
    @isconnected
    def enable_data_packet_capture(self, ports):
        '''Enable data packet capture on ports specified'''

        for port in ports.split(', '):

            # Get virtual Ixia port capture object
            captureObj = self.get_ixia_virtual_port_capture(port_name=port)

            # Enable data packet capture on port/node
            log.info("Enabling data packet capture on port '{}'".format(port))
            try:
                self.ixNet.setAttribute(captureObj, '-hardwareEnabled', 'true')
                self.ixNet.commit()
            except Exception as e:
                raise GenieTgnError("Error while enabling data packet capture "
                                    "on port '{}'".format(port))


    @BaseConnection.locked
    @isconnected
    def disable_data_packet_capture(self, ports):
        '''Disable data packet capture on ports specified'''

        for port in ports.split(', '):

            # Get virtual Ixia port capture object
            captureObj = self.get_ixia_virtual_port_capture(port_name=port)

            # Enable data packet capture on port/node
            log.info("Disabling data packet capture on port '{}'".format(port))
            try:
                self.ixNet.setAttribute(captureObj, '-hardwareEnabled', 'false')
                self.ixNet.commit()
            except Exception as e:
                raise GenieTgnError("Error while enabling data packet capture "
                                    "on port '{}'".format(port))


    @BaseConnection.locked
    @isconnected
    def enable_control_packet_capture(self, ports):
        '''Enable data packet capture on ports specified'''

        for port in ports.split(', '):

            # Get virtual Ixia port capture object
            captureObj = self.get_ixia_virtual_port_capture(port_name=port)

            # Enable data packet capture on port/node
            log.info("Enabling control packet capture on port '{}'".format(port))
            try:
                self.ixNet.setAttribute(captureObj, '-softwareEnabled', 'true')
                self.ixNet.commit()
            except Exception as e:
                raise GenieTgnError("Error while enabling data packet capture "
                                    "on port '{}'".format(port))


    @BaseConnection.locked
    @isconnected
    def disable_control_packet_capture(self, ports):
        '''Disable data packet capture on ports specified'''

        for port in ports.split(', '):

            # Get virtual Ixia port capture object
            captureObj = self.get_ixia_virtual_port_capture(port_name=port)

            # Enable data packet capture on port/node
            log.info("Disabling data packet capture on port '{}'".format(port))
            try:
                self.ixNet.setAttribute(captureObj, '-softwareEnabled', 'false')
                self.ixNet.commit()
            except Exception as e:
                raise GenieTgnError("Error while enabling data packet capture "
                                    "on port '{}'".format(port))


    @BaseConnection.locked
    @isconnected
    def start_packet_capture(self, capture_time=60):
        '''Start capturing packets for a specified amount of time'''

        log.info("Starting packet capture...")
        try:
            # Start capturing packets
            self.ixNet.execute('startCapture')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to start packet capture")

        # Time to wait after capturing packets
        log.info("Waiting for '{}' seconds after starting packet capture".\
                                                        format(capture_time))
        time.sleep(capture_time)


    @BaseConnection.locked
    @isconnected
    def stop_packet_capture(self):
        '''Stop capturing packets'''

        log.info("Stopping packet capture...")
        try:
            # Start capturing packets
            self.ixNet.execute('stopCapture')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to start packet capture")


    @BaseConnection.locked
    @isconnected
    def get_packet_capture_count(self, port_name, pcap_type):
        ''' Get the total count of packets captured during packet capture'''

        # Verify user has provided correct packet type to count
        assert pcap_type in ['data', 'control']

        # Get virtual Ixia port capture object
        captureObj = self.get_ixia_virtual_port_capture(port_name=port_name)

        if pcap_type == 'control':

            log.info("Getting total count of Control Packets...")
            try:
                packet_count = self.ixNet.getAttribute(captureObj, '-controlPacketCounter')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while getting total contol packets"
                                    " during packet capture")
            else:
                return packet_count

        elif pcap_type == 'data':

            log.info("Getting total count of Data Packets...")
            try:
                packet_count = self.ixNet.getAttribute(captureObj, '-dataPacketCounter')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while getting total contol packets"
                                    " during packet capture")
            else:
                return packet_count


    @BaseConnection.locked
    @isconnected
    def get_packet_capture_data(self, port_name):
        '''Search inside packet collected from pcap for specific data'''

        # Get virtual Ixia port capture object
        captureObj = self.get_ixia_virtual_port_capture(port_name=port_name)

        # Get current packet stack
        log.info("Getting packet capture stack on port '{}".format(port_name))
        try:
            current_packet = self.ixNet.getList(captureObj, 'currentPacket')[0]
            status = self.ixNet.execute('getPacketFromDataCapture', current_packet, 11)
            stacklist = self.ixNet.getList(current_packet, 'stack')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while getting packet capture stack")

        # Get information inside packet capture stack
        log.info("Extracting packet capture data")

        for stack in stacklist:
            try:
                # Get name of stack
                stack_name = self.ixNet.getAttribute(stack, "-displayName")
                log.info(banner(stack_name))

                # List of all the elements within data capture
                for field in self.ixNet.getList(stack, 'field'):
                    # Get the value of the field
                    name = self.ixNet.getAttribute(field, "-displayName")
                    value = self.ixNet.getAttribute(field, "-fieldValue")
                    log.info("{n} : {v}".format(n=name, v=value))
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while extracting data of packet capture")


    @BaseConnection.locked
    @isconnected
    def save_packet_capture_file(self, port_name, pcap_type, filename, directory='C:/Results'):
        '''Save packet capture file as specified filename to desired location'''

        # Verify user has provided correct packet type to count
        assert pcap_type in ['data', 'control']

        pcap_dict = {
            'data': 'HW',
            'control': 'SW',
            }

        log.info("Saving packet capture file...")
        try:
            # Save file to C:
            assert self.ixNet.execute('saveCapture', directory, '_{}'.\
                                                format(filename)) == _PASS
        except AssertionError as e:
            log.info(e)
            raise GenieTgnError("Unable to save packet capture file as '{}'".\
                                                            format(filename))

        # Return pcap file to caller
        return 'C:/Results/{port_name}_{pcap}_{f}.cap'.\
            format(port_name=port_name, pcap=pcap_dict[pcap_type], f=filename)


    @BaseConnection.locked
    @isconnected
    def export_packet_capture_file(self, src_file, dest_file):
        '''Export packet capture file as specified filename to desired location'''

        log.info("Exporting packet capture file...")
        try:
            self.ixNet.execute('copyFile',
                               self.ixNet.readFrom(src_file, '-ixNetRelative'),
                               self.ixNet.writeTo(dest_file, '-overwrite'))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to copy '{s}' to '{d}'".\
                                                format(s=src_file, d=dest_file))


    #--------------------------------------------------------------------------#
    #                        Traffic Item (Stream)                             #
    #--------------------------------------------------------------------------#

    @BaseConnection.locked
    @isconnected
    def get_traffic_stream_names(self):
        '''Returns a list of all traffic stream names present in current configuration'''

        # Init
        traffic_streams = []

        # Get traffic stream names from Ixia
        try:
            for item in self.get_traffic_stream_objects():
                traffic_streams.append(self.ixNet.getAttribute(item, '-name'))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while retrieving traffic streams from "
                                "configuration.")
        else:
            # Return to caller
            return traffic_streams


    @BaseConnection.locked
    @isconnected
    def get_traffic_stream_objects(self):
        '''Returns a list of all traffic stream objects present in current configuration'''

        # Get traffic streams from Ixia
        try:
            return self.ixNet.getList('/traffic', 'trafficItem')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while retrieving traffic streams from "
                                "configuration.")


    @BaseConnection.locked
    @isconnected
    def find_traffic_stream_object(self, traffic_stream):
        '''Finds the given stream name's traffic stream object'''

        # Init
        ti_obj = None

        # Find traffic stream object of the given traffic stream
        for item in self.get_traffic_stream_objects():
            try:
                if self.ixNet.getAttribute(item, '-name') == traffic_stream:
                    ti_obj = item
                    break
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Unable to get traffic stream object name")

        # Return to caller
        if ti_obj:
            return ti_obj
        else:
            raise GenieTgnError("Unable to find ::ixNet:: object for traffic "
                                "stream '{}'".format(traffic_stream))


    @BaseConnection.locked
    @isconnected
    def get_traffic_stream_attribute(self, traffic_stream, attribute):
        '''Returns the specified attribute for the given traffic stream'''

        # Sample attributes
        # ['name', 'state', 'txPortName', 'txPortId', 'rxPortName', 'rxPortId', 'trafficItemType']

        # Find traffic stream object
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        # Return the attribute specified for this traffic stream
        try:
            return self.ixNet.getAttribute(ti_obj, '-{}'.format(attribute))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get '{a}' for traffic stream '{t}'".\
                                format(a=attribute, t=traffic_stream))


    @BaseConnection.locked
    @isconnected
    def start_traffic_stream(self, traffic_stream, check_stream=True, wait_time=15):
        '''Start specific traffic stream on Ixia'''

        log.info(banner("Starting L2/L3 traffic for traffic stream '{}'".\
                        format(traffic_stream)))

        # Find traffic stream object from stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        try:
            # Start traffic for this stream
            self.ixNet.execute('startStatelessTraffic', ti_obj)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while starting traffic for traffic"
                                " stream '{}'".format(traffic_stream))

        # Wait for user specified interval
        log.info("Waiting for '{t}' seconds after starting traffic stream"
                 " '{s}'".format(t=wait_time, s=traffic_stream))
        time.sleep(wait_time)

        if check_stream:
            # Verify traffic stream state is now 'started'
            log.info("Verify traffic stream '{}' state is now 'started'".\
                     format(traffic_stream))
            try:
                assert 'started' == self.get_traffic_stream_attribute(traffic_stream=traffic_stream, attribute='state')
            except AssertionError as e:
                raise GenieTgnError("Traffic stream '{}' state is not 'started'".\
                                    format(traffic_stream))
            else:
                log.info("Traffic stream '{}' state is 'started'".format(traffic_stream))

            # Verify Tx Frame Rate for this stream is > 0 after starting it
            log.info("Verify Tx Frame Rate > 0 for traffic stream '{}'".\
                     format(traffic_stream))
            try:
                assert float(self.get_traffic_items_statistics_data(traffic_stream=traffic_stream, traffic_data_field='Tx Frame Rate')) > 0.0
            except AssertionError as e:
                raise GenieTgnError("Tx Frame Rate is not greater than 0 after "
                                    "starting traffic for traffic stream '{}'".\
                                    format(traffic_stream))
            else:
                log.info("Tx Frame Rate is greater than 0 after starting traffic "
                         "for traffic stream '{}'".format(traffic_stream))


    @BaseConnection.locked
    @isconnected
    def stop_traffic_stream(self, traffic_stream, wait_time=15):
        '''Stop specific traffic stream on Ixia'''

        log.info(banner("Stopping L2/L3 traffic for traffic stream '{}'".\
                        format(traffic_stream)))

        # Find traffic stream object from stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        try:
            # Stop traffic fo this stream
            self.ixNet.execute('stopStatelessTraffic', ti_obj)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while stopping traffic for traffic"
                                " stream '{}'".format(traffic_stream))

        # Wait for user specified interval
        log.info("Waiting for '{t}' seconds after stopping traffic stream"
                 " '{s}'".format(t=wait_time, s=traffic_stream))
        time.sleep(wait_time)

        # Verify traffic stream state is now 'stopped'
        log.info("Verify traffic stream '{}' state is now 'stopped'".\
                 format(traffic_stream))
        try:
            assert 'stopped' == self.get_traffic_stream_attribute(traffic_stream=traffic_stream, attribute='state')
        except AssertionError as e:
            raise GenieTgnError("Traffic stream '{}' state is not 'stopped'".\
                                format(traffic_stream))
        else:
            log.info("Traffic stream '{}' state is 'stopped'".format(traffic_stream))

        # Verify Tx Frame Rate for this stream is > 0 after starting it
        log.info("Verify Tx Frame Rate == 0 for traffic stream '{}'".\
                 format(traffic_stream))
        try:
            assert float(self.get_traffic_items_statistics_data(traffic_stream=traffic_stream, traffic_data_field='Tx Frame Rate')) == 0.0
        except AssertionError as e:
            raise GenieTgnError("Tx Frame Rate is greater than 0 after "
                                "stopping traffic for traffic stream '{}'".\
                                format(traffic_stream))
        else:
            log.info("Tx Frame Rate == 0 after stopping traffic for traffic "
                     "stream '{}'".format(traffic_stream))


    @BaseConnection.locked
    @isconnected
    def generate_traffic_stream(self, traffic_stream, wait_time=15):
        '''Generate traffic for a given traffic stream'''

        log.info(banner("Generating L2/L3 traffic for traffic stream '{}'".\
                        format(traffic_stream)))

        # Find traffic stream object from stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        # Generate traffic
        try:
            self.ixNet.execute('generate', ti_obj)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while generating traffic for traffic "
                                "stream '{}'".format(traffic_stream))

        # Unset "GENIE" view
        self._genie_view = None
        self._genie_page = None

        # Wait for user specified interval
        log.info("Waiting for '{t}' seconds after generating traffic stream"
                 " '{s}'".format(t=wait_time, s=traffic_stream))
        time.sleep(wait_time)

        # Check if traffic is in 'unapplied' state
        log.info("Checking if traffic is in 'unapplied' state...")
        try:
            assert self.get_traffic_attribute(attribute='state') == 'unapplied'
        except AssertionError as e:
            log.error(e)
            raise GenieTgnError("Traffic is not in 'unapplied' state")
        else:
            log.info("Traffic is in 'unapplied' state")


    #--------------------------------------------------------------------------#
    #                       Traffic Item Statistics                            #
    #--------------------------------------------------------------------------#

    @BaseConnection.locked
    @isconnected
    def get_traffic_items_statistics_data(self, traffic_stream, traffic_data_field):
        '''Get value of traffic_data_field of traffic_tream from "Traffic Item Statistics" '''

        # Get all stream data for given traffic_stream
        try:
            return self.ixNet.execute('getValue', 
                    '::ixNet::OBJ-/statistics/view:"Traffic Item Statistics"',
                    traffic_stream, traffic_data_field)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while retrieving '{data}' for traffic "
                                "stream '{stream}' from 'Traffic Item Statistics'".\
                                format(data=traffic_data_field, stream=traffic_stream))


    #--------------------------------------------------------------------------#
    #                            Flow Groups                                   #
    #--------------------------------------------------------------------------#

    @BaseConnection.locked
    @isconnected
    def get_flow_group_names(self, traffic_stream):
        '''Returns a list of all the flow group names for the given traffic stream present in current configuration'''

        # Init
        flow_groups = []

        # Get flow group objects of given traffic stream from Ixia
        try:
            for item in self.get_flow_group_objects():
                flow_groups.append(self.ixNet.getAttribute(item, '-name'))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while retrieving flow groups for traffic"
                                " stream '{}' from configuration.".\
                                format(traffic_stream))
        else:
            # Return to caller
            return flow_groups


    @BaseConnection.locked
    @isconnected
    def get_flow_group_objects(self, traffic_stream):
        '''Returns a list of flow group objects for the given traffic stream present in current configuration'''

        # Get traffic item object from traffic stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        # Return list of flow group highLevelStream objects
        try:
            return self.ixNet.getList(ti_obj, 'highLevelStream')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Flow groups not found in configuration for "
                                "traffic stream '{}'".format(traffic_stream))


    @BaseConnection.locked
    @isconnected
    def find_flow_group_object(self, traffic_stream, flow_group):
        '''Finds the flow group object when given the flow group name and traffic stream'''

        # Init
        fg_obj = None

        # Get flow group object of the given flow group name and traffic stream
        for item in self.get_flow_group_objects(traffic_stream=traffic_stream):
            try:
                if self.ixNet.getAttribute(item, '-name') == flow_group:
                    fg_obj = item
                    break
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Unable to get Quick Flow Group object name")

        # Return to caller
        if fg_obj:
            return fg_obj
        else:
            raise GenieTgnError("Unable to find ::ixNet:: object for Quick "
                                "Flow Group '{}'".format(flow_group))


    @BaseConnection.locked
    @isconnected
    def get_flow_group_attribute(self, traffic_stream, flow_group, attribute):
        '''Returns the specified attribute for the given flow group of the traffic stream'''

        # Sample attributes
        # ['name', 'state', 'txPortName', 'txPortId', 'rxPortName', 'rxPortId']

        # Find flow group object
        fg_obj = self.find_flow_group_object(traffic_stream=traffic_stream, flow_group=flow_group)

        # Return the attribute specified for this Quick Flow Group
        try:
            return self.ixNet.getAttribute(fg_obj, '-{}'.format(attribute))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get '{a}' for Quick Flow Group '{f}'".\
                                format(a=attribute, f=flow_group))


    @BaseConnection.locked
    @isconnected
    def start_flow_group(self, traffic_stream, flow_group, wait_time=15):
        '''Start given flow group under of traffic stream on Ixia'''

        log.info(banner("Starting traffic for flow group '{}'".\
                        format(flow_group)))

        # Find flow group object from flow group name
        fg_obj = self.find_flow_group_object(traffic_stream=traffic_stream, flow_group=flow_group)

        try:
            # Start traffic for this flow group
            self.ixNet.execute('startStatelessTraffic', fg_obj)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while starting traffic for flow group"
                                " '{}'".format(flow_group))

        # Wait for user specified interval
        log.info("Waiting for '{t}' seconds after starting traffic for flow "
                 "group '{f}'".format(t=wait_time, f=flow_group))
        time.sleep(wait_time)

        # Verify flow group state is now 'started'
        log.info("Verify flow group '{}' state is now 'started'".\
                 format(flow_group))
        try:
            assert 'started' == self.get_flow_group_attribute(traffic_stream=traffic_stream, flow_group=flow_group, attribute='state')
        except AssertionError as e:
            raise GenieTgnError("Flow group '{}' state is not 'started'".\
                                format(flow_group))
        else:
            log.info("Flow group '{}' state is 'started'".format(flow_group))


    @BaseConnection.locked
    @isconnected
    def stop_flow_group(self, traffic_stream, flow_group, wait_time=15):
        '''Stop given flow group under of traffic stream on Ixia'''

        log.info(banner("Stopping traffic for flow group '{}'".\
                        format(flow_group)))

        # Find flow group object from flow group name
        fg_obj = self.find_flow_group_object(traffic_stream=traffic_stream, flow_group=flow_group)

        try:
            # Stop traffic for this flow group
            self.ixNet.execute('stopStatelessTraffic', fg_obj)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while stopping traffic for flow group"
                                " '{}'".format(flow_group))

        # Wait for user specified interval
        log.info("Waiting for '{t}' seconds after stopping traffic for flow "
                 "group '{f}'".format(t=wait_time, f=flow_group))
        time.sleep(wait_time)

        # Verify flow group state is now 'stopped'
        log.info("Verify flow group '{}' state is now 'stopped'".\
                 format(flow_group))
        try:
            assert 'stopped' == self.get_flow_group_attribute(traffic_stream=traffic_stream, flow_group=flow_group, attribute='state')
        except AssertionError as e:
            raise GenieTgnError("Flow group '{}' state is not 'stopped'".\
                                format(flow_group))
        else:
            log.info("Flow group '{}' state is 'stopped'".format(flow_group))


    #--------------------------------------------------------------------------#
    #                          Quick Flow Groups                               #
    #--------------------------------------------------------------------------#

    @BaseConnection.locked
    @isconnected
    def get_quick_flow_group_names(self):
        '''Returns a list of all the Quick Flow Group names present in current configuration'''

        # Init
        quick_flow_groups = []

        # Get Quick Flow Group objects from Ixia
        try:
            for item in self.get_quick_flow_group_objects():
                quick_flow_groups.append(self.ixNet.getAttribute(item, '-name'))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while retrieving Quick Flow Groups from "
                                "configuration.")
        else:
            # Return to caller
            return quick_flow_groups


    @BaseConnection.locked
    @isconnected
    def get_quick_flow_group_objects(self):
        '''Returns a list of all Quick Flow Group objects present in current configuration'''

        # Init
        qfg_traffic_item = None

        # Get Quick Flow Group 'traffic stream' object
        for item in self.get_traffic_stream_objects():
            try:
                if self.ixNet.getAttribute(item, '-name') == 'Quick Flow Groups':
                    qfg_traffic_item = item
                    break
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Unable to get Quick Flow Group "
                                    "corresponding 'traffic stream' object")

        # Return list of Quick Flow Group highLevelStream objects
        if qfg_traffic_item:
            try:
                return self.ixNet.getList(qfg_traffic_item, 'highLevelStream')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Quick Flow Groups not found in configuration")
        else:
            raise GenieTgnError("Quick Flow Groups not found in configuration")


    @BaseConnection.locked
    @isconnected
    def find_quick_flow_group_object(self, quick_flow_group):
        '''Finds the Quick Flow Group object when given the Quick Flow Group name'''

        # Init
        qfg_obj = None

        # Get Quick Flow Group object of the given Quick Flow Group name
        for item in self.get_quick_flow_group_objects():
            try:
                if self.ixNet.getAttribute(item, '-name') == quick_flow_group:
                    qfg_obj = item
                    break
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Unable to get Quick Flow Group object name")

        # Return to caller
        if qfg_obj:
            return qfg_obj
        else:
            raise GenieTgnError("Unable to find ::ixNet:: object for Quick "
                                "Flow Group '{}'".format(quick_flow_group))


    @BaseConnection.locked
    @isconnected
    def get_quick_flow_group_attribute(self, quick_flow_group, attribute):
        '''Returns the specified attribute for the given Quick Flow Group'''

        # Sample attributes
        # ['name', 'state', 'txPortName', 'txPortId', 'rxPortName', 'rxPortId']

        # Find Quick Flow Group object
        qfg_obj = self.find_quick_flow_group_object(quick_flow_group=quick_flow_group)

        # Return the attribute specified for this Quick Flow Group
        try:
            return self.ixNet.getAttribute(qfg_obj, '-{}'.format(attribute))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get '{a}' for Quick Flow Group '{q}'".\
                                format(a=attribute, q=quick_flow_group))


    @BaseConnection.locked
    @isconnected
    def start_quick_flow_group(self, quick_flow_group, wait_time=15):
        '''Start given Quick Flow Group on Ixia'''

        log.info(banner("Starting traffic for Quick Flow Group '{}'".\
                        format(quick_flow_group)))

        # Find flow group object from flow group name
        qfg_obj = self.find_quick_flow_group_object(quick_flow_group=quick_flow_group)

        try:
            # Start traffic for this Quick Flow Group
            self.ixNet.execute('startStatelessTraffic', qfg_obj)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while starting traffic for Quick Flow "
                                "Group '{}'".format(quick_flow_group))

        # Wait for user specified interval
        log.info("Waiting for '{t}' seconds after starting traffic for Quick "
                 "Flow Group '{q}'".format(t=wait_time, q=quick_flow_group))
        time.sleep(wait_time)

        # Verify Quick Flow Group state is now 'started'
        log.info("Verify Quick Flow Group '{}' state is now 'started'".\
                 format(quick_flow_group))
        try:
            assert 'started' == self.get_quick_flow_group_attribute(quick_flow_group=quick_flow_group, attribute='state')
        except AssertionError as e:
            raise GenieTgnError("Quick Flow Group '{}' state is not 'started'".\
                                format(quick_flow_group))
        else:
            log.info("Quick Flow Group '{}' state is 'started'".\
                     format(quick_flow_group))


    @BaseConnection.locked
    @isconnected
    def stop_quick_flow_group(self, quick_flow_group, wait_time=15):
        '''Stop given Quick Flow Group on Ixia'''

        log.info(banner("Stopping traffic for Quick Flow Group '{}'".\
                        format(quick_flow_group)))

        # Find flow group object from flow group name
        qfg_obj = self.find_quick_flow_group_object(quick_flow_group=quick_flow_group)

        try:
            # Stop traffic for this Quick Flow Group
            self.ixNet.execute('stopStatelessTraffic', qfg_obj)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while stopping traffic for Quick Flow "
                                "Group '{}'".format(quick_flow_group))

        # Wait for user specified interval
        log.info("Waiting for '{t}' seconds after stopping traffic for Quick "
                 "Flow Group '{q}'".format(t=wait_time, q=quick_flow_group))
        time.sleep(wait_time)

        # Verify Quick Flow Group state is now 'stopped'
        log.info("Verify Quick Flow Group '{}' state is now 'stopped'".\
                 format(quick_flow_group))
        try:
            assert 'stopped' == self.get_quick_flow_group_attribute(quick_flow_group=quick_flow_group, attribute='state')
        except AssertionError as e:
            raise GenieTgnError("Quick Flow Group '{}' state is not 'stopped'".\
                                format(quick_flow_group))
        else:
            log.info("Quick Flow Group '{}' state is 'stopped'".\
                     format(quick_flow_group))


    #--------------------------------------------------------------------------#
    #                          Flow Statistics                                 #
    #--------------------------------------------------------------------------#

    @BaseConnection.locked
    @isconnected
    def get_flow_statistics_data(self, traffic_stream, flow_data_field):
        '''Get value of flow_data_field of traffic_tream from "Flow Statistics" '''

        # Get all stream data for given traffic_stream
        try:
            return self.ixNet.execute('getValue',
                            '::ixNet::OBJ-/statistics/view:"Flow Statistics"',
                            traffic_stream, flow_data_field)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while retrieving '{data}' for traffic "
                                "stream '{stream}' from 'Flow Statistics'".\
                                format(data=flow_data_field,
                                       stream=traffic_stream))


    @BaseConnection.locked
    @isconnected
    def find_flow_statistics_page_obj(self):
        '''Returns the page object for "Flow Statistics View"'''

        # Get the page object
        try:
            return self.ixNet.getList('::ixNet::OBJ-/statistics/view:"Flow Statistics"', 'page')[0]
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while finding 'Flow Statistics' view page object")


    @BaseConnection.locked
    @isconnected
    def save_flow_statistics_snapshot_csv(self, csv_windows_path="C:\\Users\\", csv_file_name="Flow_Statistics", copy_dir=runtime.directory):
        ''' Save 'Flow Statistics' snapshot as a CSV '''

        log.info(banner("Save 'Flow Statistics' snapshot CSV"))
        copy_dir = copy_dir.rstrip("/")

        # Enable CSV logging
        log.info("Enable CSV logging on Ixia...")
        try:
            self.ixNet.setAttribute('::ixNet::OBJ-/statistics', '-enableCsvLogging', 'true')
            self.ixNet.setAttribute('::ixNet::OBJ-/statistics', '-csvFilePath', csv_windows_path)
            self.ixNet.setAttribute('::ixNet::OBJ-/statistics', '-pollInterval', 1)
            self.ixNet.commit()
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while enabling CSV logging on Ixia")
        else:
            log.info("Successfully enabled CSV logging on Ixia")

        # Get snapshot options
        log.info("Get list of all snapshot options...")
        try:
            opts = self.ixNet.execute('GetDefaultSnapshotSettings')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get options")
        else:
            log.info("Successfully retreived options available")

        # Configure options settings
        filePathToChange = 'Snapshot.View.Csv.Location: ' + csv_windows_path
        opts[1] = filePathToChange
        generatingModeToChange= 'Snapshot.View.Csv.GeneratingMode: "kOverwriteCSVFile"'
        opts[2] = generatingModeToChange
        fileNameToAppend = 'Snapshot.View.Csv.Name: ' + csv_file_name
        opts.append(fileNameToAppend)

        # Save snapshot to location provided
        log.info("Save CSV snapshot of 'Flow Statistics' view to '{path}\\{file}.csv'...".\
                 format(path=csv_windows_path, file=csv_file_name))
        try:
            self.ixNet.execute('TakeViewCSVSnapshot', ["Flow Statistics"], opts)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to take CSV snapshot of 'Flow Statistics' view")
        else:
            log.info("Successfully saved CSV snapshot of 'Flow Statistics' view to:")
            log.info("{path}\\{file}".format(path=csv_windows_path, file=csv_file_name))

        # Set local and copy file paths
        self.windows_flow_stats_csv = csv_windows_path + '\\' + csv_file_name + '.csv'
        self.flow_stats_csv = copy_dir + '/' + csv_file_name + '.csv'
        #writePath = copy_dir + csv_file_name + '.csv'

        # Copy file to directory specified by user
        log.info("Copy 'Flow Statistics' CSV to '{}'".format(self.flow_stats_csv))
        try:
            self.ixNet.execute('copyFile',
                               self.ixNet.readFrom(self.windows_flow_stats_csv, '-ixNetRelative'),
                               self.ixNet.writeTo(self.flow_stats_csv, '-overwrite'))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to copy 'Flow Statistics' CSV snapshot "
                                "to '{}'".format(self.flow_stats_csv))
        else:
            log.info("Successfully copied 'Flow Statistics' CSV snapshot "
                     "to '{}'".format(self.flow_stats_csv))

        # Return to caller
        return self.flow_stats_csv


    @BaseConnection.locked
    @isconnected
    def check_flow_groups_loss(self, max_outage=120, loss_tolerance=15, rate_tolerance=5, 
                               csv_windows_path="C:\\Users\\", csv_file_name="Flow_Statistics",
                               copy_dir=runtime.directory, check_iteration=10, check_interval=60):
        '''Checks traffic loss for all flow groups configured on Ixia using
            'Flow Statistics' view data'''

        # Init
        flow_group_table = PrettyTable()
        flow_group_table.field_names = ["Flow Group Traffic Item",
                                        "VLAN:VLAN-ID",
                                        "Source/Dest Port Pair",
                                        "Tx Frame Rate",
                                        "Rx Frame Rate",
                                        "Frames Delta",
                                        "Loss %",
                                        "Outage (seconds)"]

        # Save 'Flow Statistics' view CSV snapshot
        csv_file = self.save_flow_statistics_snapshot_csv(csv_windows_path=csv_windows_path,
                                                          csv_file_name=csv_file_name,
                                                          copy_dir=copy_dir)
        # Convert CSV file into PrettyTable
        all_flow_group_data = from_csv(open(csv_file))

        # Create a table with only the values we need
        for row in all_flow_group_data:

            # Strip headers and borders
            row.header = False ; row.border = False

            # Get all the data for this row
            flow_group_name = row.get_string(fields=["Traffic Item"]).strip()
            vlan_id = row.get_string(fields=["VLAN:VLAN-ID"]).strip()
            src_dest_port_pair = row.get_string(fields=["Source/Dest Port Pair"]).strip()
            tx_frame_rate = row.get_string(fields=["Tx Frame Rate"]).strip()
            rx_frame_rate = row.get_string(fields=["Rx Frame Rate"]).strip()
            frames_delta = row.get_string(fields=["Frames Delta"]).strip()
            loss_percentage = row.get_string(fields=["Loss %"]).strip()

            # Calculate the outage
            if tx_frame_rate == '0.000' or tx_frame_rate == '0':
                outage_seconds = 0.0
            else:
                outage_seconds = round(float(frames_delta)/float(tx_frame_rate), 3)

            # Add data to the smaller table to display to user
            flow_group_table.add_row([flow_group_name, vlan_id, src_dest_port_pair, tx_frame_rate, rx_frame_rate, frames_delta, loss_percentage, outage_seconds])

        # Align and print flow groups table in the logs
        flow_group_table.align = "l"
        log.info(flow_group_table)

        # Check all flow groups for tolerances values as neede
        for i in range(check_iteration):

            log.info("\nAttempt #{}: Checking for traffic outage/loss".format(i+1))
            outage_check = True
            verified_streams = []

            # Go through each row
            for row in flow_group_table:

                # Remove headers and borders
                row.header = False ; row.border = False

                # Get stream, vlan-id and src/dest port pair
                stream = row.get_string(fields=["Flow Group Traffic Item"]).strip()
                vlan = row.get_string(fields=["VLAN:VLAN-ID"]).strip()
                pair = row.get_string(fields=["Source/Dest Port Pair"]).strip()

                # Verify outage for traffic stream
                if not self.verify_flow_group_outage(traffic_stream=stream,
                                                     vlan_id=vlan,
                                                     source_dest_pair=pair,
                                                     flow_group_table=flow_group_table,
                                                     max_outage=max_outage,
                                                     loss_tolerance=loss_tolerance,
                                                     rate_tolerance=rate_tolerance):
                    # Traffic loss observed for stream
                    outage_check = False

            # Check if iteration required based on results
            if outage_check:
                log.info("\nSuccessfully verified traffic outages/loss is within "
                         "tolerance for given traffic streams")
                break
            elif i == check_iteration or i == check_iteration-1:
                # End of iterations, raise Exception and exit
                raise GenieTgnError("\nUnexpected traffic outage/loss is "
                                    "observed for flow groups")
            else:
                # Traffic loss observed, sleep and recheck
                log.error("\nSleeping '{s}' seconds and rechecking flow group "
                          "streams for traffic outage/loss".\
                          format(s=check_interval))
                time.sleep(check_interval)


    @BaseConnection.locked
    @isconnected
    def verify_flow_group_outage(self, traffic_stream, vlan_id, source_dest_pair, flow_group_table, max_outage=120, loss_tolerance=15, rate_tolerance=5):
        '''For each flow group configured on Ixia:
            * 1- Verify traffic outage (in seconds) is less than tolerance threshold
            * 2- Verify current loss % is less than tolerance threshold
            * 3- Verify difference between Tx Rate & Rx Rate is less than tolerance threshold
        '''

        log.info(banner("Checking flow group: '{t} | {vlan} | {pair}'".\
                        format(t=traffic_stream, vlan=vlan_id, pair=source_dest_pair)))

        # Init
        outage_check = False
        loss_check = False
        rate_check = False

        # Loop over all flow groups in configuration
        for row in flow_group_table:

            # Remove headers and borders
            row.header = False ; row.border = False

            # Get stream name and source dest/port pair
            current_stream = row.get_string(fields=["Flow Group Traffic Item"]).strip()
            current_vlan_id = row.get_string(fields=["VLAN:VLAN-ID"]).strip()
            current_srcdest_pair = row.get_string(fields=["Source/Dest Port Pair"]).strip()

            # Get row in table associated with unique flow group
            if traffic_stream != current_stream or current_vlan_id != vlan_id or\
               current_srcdest_pair != source_dest_pair:
                continue

            # 1- Verify traffic Outage (in seconds) is less than tolerance threshold
            log.info("1. Verify traffic outage (in seconds) is less than "
                     "tolerance threshold of '{}' seconds".format(max_outage))
            outage = row.get_string(fields=["Outage (seconds)"]).strip()
            if float(outage) <= float(max_outage):
                log.info("* Traffic outage of '{o}' seconds is within "
                         "expected maximum outage threshold of '{s}' seconds".\
                         format(o=outage, s=max_outage))
                outage_check = True
            else:
                log.error("* Traffic outage of '{o}' seconds is *NOT* within "
                          "expected maximum outage threshold of '{s}' seconds".\
                          format(o=outage, s=max_outage))

            # 2- Verify current loss % is less than tolerance threshold
            log.info("2. Verify current loss % is less than tolerance "
                     "threshold of '{}' %".format(loss_tolerance))
            if row.get_string(fields=["Loss %"]).strip() != '':
                loss_percentage = row.get_string(fields=["Loss %"]).strip()
            else:
                loss_percentage = 0

            # Check traffic loss
            if float(loss_percentage) <= float(loss_tolerance):
                log.info("* Current traffic loss of {l}% is within"
                         " maximum expected loss tolerance of {t}%".\
                         format(t=loss_tolerance, l=loss_percentage))
                loss_check = True
            else:
                log.error("* Current traffic loss of {l}% is *NOT* within"
                          " maximum expected loss tolerance of {t}%".\
                          format(t=loss_tolerance, l=loss_percentage))

            # 3- Verify difference between Tx Rate & Rx Rate is less than tolerance threshold
            log.info("3. Verify difference between Tx Rate & Rx Rate is less "
                     "than tolerance threshold of '{}' pps".format(rate_tolerance))
            tx_rate = row.get_string(fields=["Tx Frame Rate"]).strip()
            rx_rate = row.get_string(fields=["Rx Frame Rate"]).strip()
            if abs(float(tx_rate) - float(rx_rate)) <= float(rate_tolerance):
                log.info("* Difference between Tx Rate '{t}' and Rx Rate"
                         " '{r}' is within expected maximum rate loss"
                         " threshold of '{m}' packets per second".\
                         format(t=tx_rate, r=rx_rate, m=rate_tolerance))
                rate_check = True
            else:
                log.error("* Difference between Tx Rate '{t}' and Rx Rate"
                          " '{r}' is *NOT* within expected maximum rate loss"
                          " threshold of '{m}' packets per second".\
                          format(t=tx_rate, r=rx_rate, m=rate_tolerance))

            # Checks completed, avoid checking other streams with duplicate names
            break

        # If all streams had:
        #   1- No traffic outage beyond threshold
        #   2- No current loss beyond threshold
        #   3- No frames rate loss
        if outage_check and loss_check and rate_check:
            log.info("Flow group '{t} | {v} | {p}': traffic outage, loss% and "
                     "Tx/Rx Rate difference within maximum expected threshold".\
                     format(t=traffic_stream, v=vlan_id, p=source_dest_pair))
            return True
        else:
            log.error("Flow group {t} | {v} | {p}': traffic outage, loss% and "
                      "Tx/Rx Rate difference *NOT* within maximum expected threshold".\
                      format(t=traffic_stream, v=vlan_id, p=source_dest_pair))
            return False



    #--------------------------------------------------------------------------#
    #                     Line / Packet / Layer2-bit Rate                      #
    #--------------------------------------------------------------------------#

    @BaseConnection.locked
    @isconnected
    def set_line_rate(self, traffic_stream, rate, flow_group='', stop_traffic_time=15, generate_traffic_time=15, apply_traffic_time=15, start_traffic_time=15):
        '''Set the line rate for given traffic stream or given flow group of a traffic stream'''

        # Verify rate value provided is <=100 as line rate is a percentage
        try:
            assert rate in range(100)
        except AssertionError as e:
            raise GenieTgnError("Invalid input rate={} provided. Line rate must"
                                " be between 0 to 100%".format(rate))

        # Get traffic item object from stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        if flow_group:
            # Set the line rate for given flow group of this traffic item
            log.info(banner("Setting flow group '{f}' of traffic stream '{t}' "
                            "line rate to '{r}' %".format(f=flow_group,
                                                        t=traffic_stream,
                                                        r=rate)))

            # Get flow group object of the given traffic stream
            flowgroupObj = self.get_flow_group_object(traffic_stream=traffic_stream, flow_group=flow_group)

            # Change the line rate as required
            try:
                self.ixNet.setMultiAttribute(flowgroupObj + '/frameRate',
                                             '-rate', rate,
                                             '-type', 'percentLineRate')
                self.ixNet.commit()
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while changing flow group '{f}' of "
                                    "traffic stream '{t}' line rate to '{r}' %".\
                                    format(f=flow_group, t=traffic_stream, r=rate))
            else:
                log.info("Successfully changed flow group '{f}' of traffic "
                         "stream '{t}' line rate to '{r}'".format(f=flow_group,
                                                                  t=traffic_stream,
                                                                  r=rate))
        else:
            # Set the line rate for the entire traffic stream
            log.info(banner("Setting traffic stream '{t}' line rate to '{r}' %".\
                            format(t=traffic_stream, r=rate)))

            # Initial state
            initial_state = self.get_traffic_attribute(attribute='state')

            # Stop traffic for the given stream
            if initial_state == 'started':
                self.stop_traffic(wait_time=stop_traffic_time)
            else:
                self.stop_traffic_stream(traffic_stream=traffic_stream, wait_time=stop_traffic_time)

            # Get config element object
            try:
                config_elements = self.ixNet.getList(ti_obj, 'configElement')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Unable to get config elements for traffic "
                                    "stream '{}'".format(traffic_stream))

            for config_element in config_elements:
                try:
                    self.ixNet.setMultiAttribute(config_element + '/frameRate',
                                                 '-rate', rate,
                                                 '-type', 'percentLineRate')
                    self.ixNet.commit()
                except Exception as e:
                    log.error(e)
                    raise GenieTgnError("Error while changing traffic stream "
                                        "'{t}' line rate to '{r}' %".\
                                        format(t=traffic_stream, r=rate))
                else:
                    log.info("Successfully changed traffic stream '{t}' line "
                             "rate to '{r}' %".format(t=traffic_stream, r=rate))

            # Generate traffic
            self.generate_traffic_stream(traffic_stream=traffic_stream, wait_time=generate_traffic_time)

            # Apply traffic
            self.apply_traffic(wait_time=apply_traffic_time)

            # Start traffic
            if initial_state == 'started':
                self.start_traffic(wait_time=start_traffic_time)
            else:
                self.start_traffic_stream(traffic_stream=traffic_stream, wait_time=start_traffic_time)


    @BaseConnection.locked
    @isconnected
    def set_packet_rate(self, traffic_stream, rate, flow_group='', stop_traffic_time=15, generate_traffic_time=15, apply_traffic_time=15, start_traffic_time=15):
        '''Set the packet rate for given traffic stream or given flow group of a traffic stream'''

        # Get traffic item object from stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        if flow_group:
            # Set the packet rate for given flow group of this traffic item
            log.info(banner("Setting flow group '{f}' of traffic stream '{t}' "
                            "packet rate to '{r}' frames per second".\
                            format(f=flow_group, t=traffic_stream, r=rate)))

            # Get flow group object of the given traffic stream
            flowgroupObj = self.get_flow_group_object(traffic_stream=traffic_stream, flow_group=flow_group)

            # Change the packet rate as required
            try:
                self.ixNet.setMultiAttribute(flowgroupObj + '/frameRate',
                                             '-rate', rate,
                                             '-type', 'framesPerSecond')
                self.ixNet.commit()
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while changing flow group '{f}' of "
                                    "traffic stream '{t}' packet rate to '{r}'".\
                                    format(f=flow_group, t=traffic_stream, r=rate))
            else:
                log.info("Successfully changed flow group '{f}' of traffic "
                         "stream '{t}' packet rate to '{r}' frames per second".\
                         format(f=flow_group, t=traffic_stream, r=rate))
        else:
            # Set the packet rate for the entire traffic stream
            log.info(banner("Setting traffic stream '{t}' packet rate to '{r}'"
                            " frames per second".format(t=traffic_stream, r=rate)))

            # Initial state
            initial_state = self.get_traffic_attribute(attribute='state')

            # Stop traffic for the given stream
            if initial_state == 'started':
                self.stop_traffic(wait_time=stop_traffic_time)
            else:
                self.stop_traffic_stream(traffic_stream=traffic_stream, wait_time=stop_traffic_time)

            # Get config element object
            try:
                config_elements = self.ixNet.getList(ti_obj, 'configElement')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Unable to get config elements for traffic "
                                    "stream '{}'".format(traffic_stream))

            for config_element in config_elements:
                try:
                    self.ixNet.setMultiAttribute(config_element + '/frameRate',
                                                 '-rate', rate,
                                                 '-type', 'framesPerSecond')
                    self.ixNet.commit()
                except Exception as e:
                    log.error(e)
                    raise GenieTgnError("Error while changing traffic stream "
                                        "'{t}' packet rate to '{r}' frames per "
                                        "second".format(t=traffic_stream, r=rate))
                else:
                    log.info("Successfully changed traffic stream '{t}' packet "
                             "rate to '{r}' frames per second".\
                             format(t=traffic_stream, r=rate))

            # Generate traffic
            self.generate_traffic_stream(traffic_stream=traffic_stream, wait_time=generate_traffic_time)

            # Apply traffic
            self.apply_traffic(wait_time=apply_traffic_time)

            # Start traffic
            if initial_state == 'started':
                self.start_traffic(wait_time=start_traffic_time)
            else:
                self.start_traffic_stream(traffic_stream=traffic_stream, wait_time=start_traffic_time)


    @BaseConnection.locked
    @isconnected
    def set_layer2_bit_rate(self, traffic_stream, rate, rate_unit, flow_group='', stop_traffic_time=15, generate_traffic_time=15, apply_traffic_time=15, start_traffic_time=15):
        '''Set the Layer2 bit rate for given traffic stream or given flow group
           within the traffic stream'''

        # Define units_dict
        units_dict = {
            'bps': 'bitsPerSec',
            'Kbps': 'kbitsPerSec',
            'Mbps': 'mbitsPerSec',
            'Bps': 'bytesPerSec',
            'KBps': 'kbytesPerSec',
            'MBps': 'mbytesPerSec',
            }

        # Verify valid units have been passed in
        try:
            assert rate_unit in ['bps', 'Kbps', 'Mbps', 'Bps', 'KBps', 'MBps']
        except AssertionError as e:
            raise GenieTgnError("Invalid unit '{}' passed in for layer2 bit rate".\
                                format(rate_unit))

        # Get traffic item object from stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        if flow_group:
            # Set the layer2 bit rate for given flow group of this traffic item
            log.info(banner("Setting flow group '{f}' of traffic stream '{t}' "
                            "layer2 bit rate to '{r}' {u}".format(f=flow_group,
                                                                  t=traffic_stream,
                                                                  r=rate,
                                                                  u=rate_unit)))

            # Get flow group object of the given traffic stream
            flowgroupObj = self.get_flow_group_object(traffic_stream=traffic_stream, flow_group=flow_group)

            # Change the layer2 bit rate as required
            try:
                self.ixNet.setMultiAttribute(flowgroupObj + '/frameRate',
                                             '-rate', rate,
                                             '-bitRateUnitsType', units_dict[rate_unit],
                                             '-type', 'bitsPerSecond')
                self.ixNet.commit()
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while changing flow group '{f}' of "
                                    "traffic stream '{t}' layer2 bit rate to "
                                    "'{r}' {u}".format(f=flow_group,
                                                       t=traffic_stream,
                                                       r=rate,
                                                       u=rate_unit))
            else:
                log.info("Successfully changed flow group '{f}' of traffic "
                         "stream '{t}' layer2 bit rate to '{r}' {u}".\
                         format(f=flow_group, t=traffic_stream, r=rate, u=rate_unit))
        else:
            # Set the layer2 bit rate for the entire traffic stream
            log.info(banner("Setting traffic stream '{t}' layer2 bit rate to"
                            " '{r}' {u}".format(t=traffic_stream, r=rate, u=rate_unit)))

            # Initial state
            initial_state = self.get_traffic_attribute(attribute='state')

            # Stop traffic for the given stream
            if initial_state == 'started':
                self.stop_traffic(wait_time=stop_traffic_time)
            else:
                self.stop_traffic_stream(traffic_stream=traffic_stream, wait_time=stop_traffic_time)

            # Get config element object
            try:
                config_elements = self.ixNet.getList(ti_obj, 'configElement')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Unable to get config elements for traffic "
                                    "stream '{}'".format(traffic_stream))

            for config_element in config_elements:
                try:
                    self.ixNet.setMultiAttribute(config_element + '/frameRate',
                                                 '-rate', rate,
                                                 '-bitRateUnitsType', units_dict[rate_unit],
                                                 '-type', 'bitsPerSecond')
                    self.ixNet.commit()
                except Exception as e:
                    log.error(e)
                    raise GenieTgnError("Error while changing traffic stream "
                                        "'{t}' layer2 bit rate to '{r}' {u}".\
                                        format(t=traffic_stream,
                                               r=rate,
                                               u=rate_unit))
                else:
                    log.info("Successfully changed traffic stream '{t}' layer2 "
                             "bit rate to '{r}' {u}".format(t=traffic_stream,
                                                            r=rate,
                                                            u=rate_unit))

            # Generate traffic
            self.generate_traffic_stream(traffic_stream=traffic_stream, wait_time=generate_traffic_time)

            # Apply traffic
            self.apply_traffic(wait_time=apply_traffic_time)

            # Start traffic
            if initial_state == 'started':
                self.start_traffic(wait_time=start_traffic_time)
            else:
                self.start_traffic_stream(traffic_stream=traffic_stream, wait_time=start_traffic_time)


    @BaseConnection.locked
    @isconnected
    def set_packet_size_fixed(self, traffic_stream, packet_size, stop_traffic_time=15, generate_traffic_time=15, apply_traffic_time=15, start_traffic_time=15):
        '''Set the packet size for given traffic stream'''

        # Get traffic item object from stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        # Set the packet size for the traffic stream
        log.info(banner("Setting traffic stream '{t}' packet size to '{p}'".\
                        format(t=traffic_stream, p=packet_size)))

        # Initial state
        initial_state = self.get_traffic_attribute(attribute='state')

        # Stop traffic for the given stream
        if initial_state == 'started':
            self.stop_traffic(wait_time=stop_traffic_time)
        else:
            self.stop_traffic_stream(traffic_stream=traffic_stream, wait_time=stop_traffic_time)

        # Get config element object
        try:
            config_elements = self.ixNet.getList(ti_obj, 'configElement')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get config elements for traffic "
                                "stream '{}'".format(traffic_stream))

        for config_element in config_elements:
            try:
                self.ixNet.setMultiAttribute(config_element + '/frameSize',
                                             '-fixedSize', packet_size)
                self.ixNet.commit()
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while changing traffic stream "
                                    "'{t}' packet size to '{p}'".\
                                    format(t=traffic_stream, p=packet_size))
            else:
                log.info("Successfully changed traffic stream '{t}' packet "
                         "size to '{p}'".format(t=traffic_stream, p=packet_size))

        # Generate traffic
        self.generate_traffic_stream(traffic_stream=traffic_stream, wait_time=generate_traffic_time)

        # Apply traffic
        self.apply_traffic(wait_time=apply_traffic_time)

        # Start traffic
        if initial_state == 'started':
            self.start_traffic(wait_time=start_traffic_time)
        else:
            self.start_traffic_stream(traffic_stream=traffic_stream, wait_time=start_traffic_time)


    @BaseConnection.locked
    @isconnected
    def get_line_rate(self, traffic_stream, flow_group=''):
        '''Returns the line rate for given traffic stream or flow group'''

        # Init
        line_rate = None

        # Get traffic item object from stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        if flow_group:
            # Get flow group object of the given traffic stream
            flowgroupObj = self.get_flow_group_object(traffic_stream=traffic_stream, flow_group=flow_group)

            # Set attribute to be the line rate
            try:
                self.ixNet.setAttribute(flowgroupObj + '/frameRate',
                                        '-type', 'percentLineRate')
                self.ixNet.commit()
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while getting line rate for flow "
                                    "group '{}'".format(flow_group))

            # Get the line rate
            try:
                line_rate = self.ixNet.getAttribute(flowgroupObj, '-rate')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while getting line rate for flow "
                                    "group '{}'".format(flow_group))

            # Return to caller
            if line_rate:
                return line_rate
            else:
                raise GenieTgnError("Unable to find line rate for flow "
                                    "group '{}".format(flow_group))
        else:
            # Get config element object
            try:
                config_elements = self.ixNet.getList(ti_obj, 'configElement')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Unable to get config elements for traffic "
                                    "stream '{}'".format(traffic_stream))

            for config_element in config_elements:
                # Set attribute to be the line rate
                try:
                    self.ixNet.setAttribute(config_element + '/frameRate',
                                            '-type', 'percentLineRate')
                    self.ixNet.commit()
                except Exception as e:
                    log.error(e)
                    raise GenieTgnError("Error while getting line rate for "
                                        "traffic stream '{}'".format(traffic_stream))

                # Get the line rate
                try:
                    line_rate = self.ixNet.getAttribute(config_element + '/frameRate', '-rate')
                except Exception as e:
                    log.error(e)
                    raise GenieTgnError("Error while getting line rate for "
                                        "traffic stream '{}'".format(traffic_stream))

            # Return to caller
            if line_rate:
                return line_rate
            else:
                raise GenieTgnError("Unable to find line rate for traffic "
                                    "stream '{}".format(traffic_stream))


    @BaseConnection.locked
    @isconnected
    def get_packet_rate(self, traffic_stream, flow_group=''):
        '''Returns the packet rate for given traffic stream or flow group'''

        # Init
        packet_rate = None

        # Get traffic item object from stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        if flow_group:
            # Get flow group object of the given traffic stream
            flowgroupObj = self.get_flow_group_object(traffic_stream=traffic_stream, flow_group=flow_group)

            # Set attribute to be the packet rate
            try:
                self.ixNet.setAttribute(flowgroupObj + '/frameRate',
                                        '-type', 'framesPerSecond')
                self.ixNet.commit()
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while getting packet rate for flow "
                                    "group '{}'".format(flow_group))

            # Get the packet rate
            try:
                packet_rate = self.ixNet.getAttribute(flowgroupObj, '-rate')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while getting packet rate for flow "
                                    "group '{}'".format(flow_group))

            # Return to caller
            if packet_rate:
                return packet_rate
            else:
                raise GenieTgnError("Unable to find packet rate for flow "
                                    "group '{}".format(flow_group))
        else:
            # Get config element object
            try:
                config_elements = self.ixNet.getList(ti_obj, 'configElement')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Unable to get config elements for traffic "
                                    "stream '{}'".format(traffic_stream))

            for config_element in config_elements:
                # Set attribute to be the packet rate
                try:
                    self.ixNet.setAttribute(config_element + '/frameRate',
                                            '-type', 'framesPerSecond')
                    self.ixNet.commit()
                except Exception as e:
                    log.error(e)
                    raise GenieTgnError("Error while getting packet rate for "
                                        "traffic stream '{}'".format(traffic_stream))

                # Get the packet rate
                try:
                    packet_rate = self.ixNet.getAttribute(config_element + '/frameRate', '-rate')
                except Exception as e:
                    log.error(e)
                    raise GenieTgnError("Error while getting packet rate for "
                                        "traffic stream '{}'".format(traffic_stream))

            # Return to caller
            if packet_rate:
                return packet_rate
            else:
                raise GenieTgnError("Unable to find packet rate for traffic "
                                    "stream '{}".format(traffic_stream))


    @BaseConnection.locked
    @isconnected
    def get_layer2_bit_rate(self, traffic_stream, flow_group=''):
        '''Returns the layer2 bit rate given traffic stream or flow group'''

        # Init
        layer2bit_rate = None

        # Get traffic item object from stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        if flow_group:
            # Get flow group object of the given traffic stream
            flowgroupObj = self.get_flow_group_object(traffic_stream=traffic_stream, flow_group=flow_group)

            # Set attribute to be the layer2 bit rate
            try:
                self.ixNet.setAttribute(flowgroupObj + '/frameRate',
                                        '-type', 'bitsPerSecond')
                self.ixNet.commit()
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while getting layer2 bit rate for "
                                    "flow group '{}'".format(flow_group))

            # Get the layer2 bit rate
            try:
                layer2bit_rate = self.ixNet.getAttribute(flowgroupObj, '-rate')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while getting layer2 bit rate for "
                                    "flow group '{}'".format(flow_group))

            # Return to caller
            if layer2bit_rate:
                return layer2bit_rate
            else:
                raise GenieTgnError("Unable to find layer2 bit rate for flow "
                                    "group '{}".format(flow_group))
        else:
            # Get config element object
            try:
                config_elements = self.ixNet.getList(ti_obj, 'configElement')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Unable to get config elements for traffic "
                                    "stream '{}'".format(traffic_stream))

            for config_element in config_elements:
                # Set attribute to be the layer2 bit rate
                try:
                    self.ixNet.setAttribute(config_element + '/frameRate',
                                            '-type', 'bitsPerSecond')
                    self.ixNet.commit()
                except Exception as e:
                    log.error(e)
                    raise GenieTgnError("Error while getting layer2 bit rate for "
                                        "traffic stream '{}'".format(traffic_stream))

                # Get the layer2 bit rate
                try:
                    layer2bit_rate = self.ixNet.getAttribute(config_element + '/frameRate', '-rate')
                except Exception as e:
                    log.error(e)
                    raise GenieTgnError("Error while getting layer2 bit rate for "
                                        "traffic stream '{}'".format(traffic_stream))

            # Return to caller
            if layer2bit_rate:
                return layer2bit_rate
            else:
                raise GenieTgnError("Unable to find packet rate for traffic "
                                    "stream '{}".format(traffic_stream))


    @BaseConnection.locked
    @isconnected
    def get_packet_size(self, traffic_stream):
        '''Returns the packet size for given traffic stream'''

        # Init
        packet_size = None

        # Get traffic item object from stream name
        ti_obj = self.find_traffic_stream_object(traffic_stream=traffic_stream)

        # Get config element object
        try:
            config_elements = self.ixNet.getList(ti_obj, 'configElement')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get config elements for traffic "
                                "stream '{}'".format(traffic_stream))

        for config_element in config_elements:
            try:
                packet_size = self.ixNet.getAttribute(config_element + '/frameSize', '-fixedSize')
            except Exception as e:
                log.error(e)
                raise GenieTgnError("Error while getting the packet size for"
                                    " '{p}'".format(t=traffic_stream))

        # Return to caller
        if packet_size:
            return packet_size
        else:
            raise GenieTgnError("Unable to find packet rate for traffic "
                                "stream '{}".format(traffic_stream))


    #--------------------------------------------------------------------------#
    #                               QuickTest                                  #
    #--------------------------------------------------------------------------#

    @BaseConnection.locked
    @isconnected
    def find_quicktest_object(self, quicktest):
        '''Finds and returns the QuickTest object for the specific test'''

        # Ensure valid QuickTest types have been passed in
        try:
            assert quicktest in self.valid_quicktests
        except AssertionError as e:
            raise GenieTgnError("Invalid QuickTest '{q}' provided.\nValid "
                                "options are {l}".format(q=quicktest, l=self.valid_quicktests))

        # Get QuickTest root
        qt_root = None
        try:
            qt_root = self.ixNet.getList(self.ixNet.getRoot(), 'quickTest')[0]
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get QuickTest root object")

        # Get list of QuickTests configured on Ixia
        try:
            qt_list = self.ixNet.getAttribute(qt_root, '-testIds')
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get list of QuickTests configured")

        # Get specific QuickTest test
        qt_obj = None
        for item in qt_list:
            if quicktest in item:
                qt_obj = item
                break

        # Return to caller
        if qt_obj:
            return qt_obj
        else:
            raise GenieTgnError("Unable to find ::ixNet:: object for QuickTest "
                                "'{}'".format(quicktest))


    @BaseConnection.locked
    @isconnected
    def get_quicktest_results_attribute(self, quicktest, attribute):
        '''Returns the value of specified quicktest results attribute '''

        # Verify valid attribute provided
        try:
            assert attribute in ['isRunning',
                                 'status',
                                 'progress',
                                 'result',
                                 'resultPath',
                                 'startTime',
                                 'duration']
        except AssertionError as e:
            raise GenieTgnError("Invalid attribute '{}' provided for Quicktest "
                                "results".format(attribute))

        # Get QuickTest object
        qt_obj = self.find_quicktest_object(quicktest=quicktest)

        # Return attribute value
        try:
            return self.ixNet.getAttribute(qt_obj+'/results', '-{}'.format(attribute))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to get value of Quicktest results "
                                "attribute '{}'".format(attribute))


    @BaseConnection.locked
    @isconnected
    def load_quicktest_configuration(self, configuration, wait_time=30):
        '''Load QuickTest configuration file'''

        log.info(banner("Loading Quicktest configuration..."))

        # Load the QuickTest configuration file onto Ixia
        try:
            load_config = self.ixNet.execute('loadConfig',
                                             self.ixNet.readFrom(configuration))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to load Quicktest configuration file "
                                "'{f}' onto device '{d}'".format(f=configuration,
                                d=self.device.name)) from e

        # Verify return
        try:
            assert load_config == _PASS
        except AssertionError as e:
            log.error(load_config)
            raise GenieTgnError("Unable to load Quicktest configuration file "
                                "'{f}' onto device '{d}'".format(f=configuration,
                                d=self.device.name)) from e
        else:
            log.info("Successfully loaded Quicktest configuration file '{f}' "
                     "onto device '{d}'".format(f=configuration,
                     d=self.device.name))

        # Wait after loading configuration file
        log.info("Waiting for '{}' seconds after loading configuration...".\
                 format(wait_time))
        time.sleep(wait_time)

        # Verify traffic is in 'unapplied' state
        log.info("Verify traffic is in 'unapplied' state after loading configuration")
        try:
            assert self.get_traffic_attribute(attribute='state') == 'unapplied'
        except AssertionError as e:
            raise GenieTgnError("Traffic is not in 'unapplied' state after "
                                "loading configuration onto device '{}'".\
                                format(self.device.name)) from e
        else:
            log.info("Traffic in 'unapplied' state after loading configuration "
                     "onto device '{}'".format(self.device.name))


    @BaseConnection.locked
    @isconnected
    def execute_quicktest(self, quicktest, apply_wait=60, exec_wait=1800, exec_interval=300, save_location="C:\\Users\\"):
        '''Execute specific RFC QuickTest'''

        log.info(banner("Prepare execution of Quicktest '{}'...".\
                        format(quicktest)))

        # Get QuickTest object
        qt_obj = self.find_quicktest_object(quicktest=quicktest)

        # Apply QuickTest configuration
        log.info("Apply QuickTest '{}' configuration".format(quicktest))
        try:
            apply_qt = self.ixNet.execute('apply', qt_obj)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to apply traffic configuration for "
                                "QuickTest '{}'".format(quicktest))

        # Verify QuickTest configuration application passed
        try:
            assert apply_qt == _PASS
        except AssertionError as e:
            log.error(apply_qt)
            raise GenieTgnError("Unable to apply QuickTest '{}' configuration".\
                                format(quicktest))
        else:
            log.info("Successfully applied QuickTest '{}' configuration".\
                     format(quicktest))

        # Wait after applying QuickTest configuration
        log.info("Waiting '{}' seconds after applying QuickTest "
                 "configuration".format(apply_wait))
        time.sleep(apply_wait)

        # Enable QuickTest report
        log.info("Enable QuickTest '{}' report generation".format(quicktest))
        try:
            self.ixNet.setMultiAttribute('::ixNet::OBJ-/quickTest/globals',
                                         '-enableGenerateReportAfterRun', 'true',
                                         '-useDefaultRootPath', 'false',
                                         '-outputRootPath', save_location,
                                         '-titlePageComments',
                                         "QuickTest RFC2544 Test Result")
            self.ixNet.commit()
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Error while enabling PDF report genaration")
        else:
            log.info("Successfully enabled QuickTest '{}' report generation".\
                     format(quicktest))

        # Start QuickTest execution
        log.info("Start execution of QuickTest '{}'".format(quicktest))
        try:
            start_qt = self.ixNet.execute('start', qt_obj)
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to start execution of Quicktest"
                                " '{}'".format(quicktest))

        # Verify QuickTest successfully started
        try:
            assert start_qt == _PASS
        except AssertionError as e:
            log.error(start_qt)
            raise GenieTgnError("Unable to start execution of QuickTest '{}'".\
                                format(quicktest))
        else:
            log.info("Successfully started execution of QuickTest '{}'".\
                     format(quicktest))

        # Poll until execution has completed
        log.info("Poll until Quicktest '{}' execution completes".format(quicktest))
        timeout = Timeout(max_time=exec_wait, interval=exec_interval)
        while timeout.iterate():
            if self.get_quicktest_results_attribute(quicktest=quicktest, attribute='isRunning') == 'false':
                break

        # Print test exeuction duration to user
        duration = self.get_quicktest_results_attribute(quicktest=quicktest, attribute='duration')
        start_time = self.get_quicktest_results_attribute(quicktest=quicktest, attribute='startTime')
        result = self.get_quicktest_results_attribute(quicktest=quicktest, attribute='result')
        log.info("Quicktest '{}' execution completed:".format(quicktest))
        log.info("-> Test Duration = {d}\n"
                 "-> Start Time = {s}\n"
                 "-> Overall Result = {r}".\
                 format(q=quicktest, d=duration, s=start_time, r=result))


    @BaseConnection.locked
    @isconnected
    def generate_quicktest_report(self, quicktest, save_location="C:\\Users\\"):
        '''Generate QuickTest PDF report and return the location'''

        log.info(banner("Generating PDF report for Quicktest {}...".\
                        format(quicktest)))

        # Get QuickTest object
        qt_obj = self.find_quicktest_object(quicktest=quicktest)

        # Set the folder name of where we want the PDF report to be saved under resultPath
        try:
            self.ixNet.setAttribute('::ixNet::OBJ-/quickTest/globals', '-outputRootPath', save_location)
            self.ixNet.commit()
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to set PDF report directory to {}".\
                                format(save_location))
        else:
            log.info("Successfully set PDF report directory to {}".\
                     format(save_location))

        # Generate the PDF report
        try:
            self.ixNet.execute('generateReport', qt_obj)
            self.ixNet.commit()
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to generate PDF report for Quicktest"
                                " '{}'".format(quicktest))
        else:
            log.info("Successfully generated PDF report for Quicktest '{}'".\
                     format(quicktest))

        # Get QuickTest report results path
        return self.get_quicktest_results_attribute(quicktest=quicktest,
                                                    attribute='resultPath')


    @BaseConnection.locked
    @isconnected
    def export_quicktest_report(self, src_file, dest_file):
        '''Export QuickTest PDF report to given destination'''

        log.info(banner("Exporting Quicktest PDF report"))

        # Exporting the QuickTest PDF file
        try:
            self.ixNet.execute('copyFile',
                               self.ixNet.readFrom(src_file, '-ixNetRelative'),
                               self.ixNet.writeTo(dest_file, '-overwrite'))
        except Exception as e:
            log.error(e)
            raise GenieTgnError("Unable to export Quicktest PDF report from"
                                " '{s}' to '{d}'".format(s=src_file, d=dest_file))


