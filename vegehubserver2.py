#!/usr/bin/env python3
# Author: Nick Waterton <n.waterton@outlook.com>
# Description: MQTT interface to Vegehub Sensor Hub
# NOTE: if the server is down for any length of time (or does not respond), the vegehub will store readings,
# then send them all at once when the server connection is re-established.

#see https://vegecloud.com/Documentation/HubConfigApi.phtml for protocol details

# N Waterton 27th May 2021 V2.0: async re-write to support firmware V3.9 which allows for vegehub config updates

import logging
from logging.handlers import RotatingFileHandler
global HAVE_MQTT
HAVE_MQTT = False
try:
    import paho.mqtt.client as paho
    HAVE_MQTT = True
except ImportError:
    print("paho mqtt client not found")
import os, sys, json, math
import socket
import signal
import datetime as dt
import asyncio
from aiohttp import web

__VERSION__ = __version__ = '2.0'

class vegehubserver():

    __VERSION__ = __version__ = __VERSION__

    def __init__(self, webport=None, log=None, arg=None):
        if log:
            self.log = log
        else:
            self.log = logging.getLogger("Vegehub.api")
        self.loop = asyncio.get_event_loop()
        self.webport = webport
        if not isinstance(self.webport, list):
            self.webport = [self.webport]
        self.config_file = arg.config if arg else 'config.json'
        self.settings = self.load_settings()
        self.app = None
        self.web_task = []#None
        self.mqttc = None
        self.remote_host = None
        self.arg = arg
        if self.arg:
            try:
                self.mqttc = self.setup_mqtt_client(arg.broker, arg.port, arg.user, arg.password, arg.pub_topic, arg.sub_topic)
            except Exception as e:
                self.log.exception(e)
        self.decode_topics(self.settings)
        self.start_web()
            
    def setup_mqtt_client(self, broker=None,
                                 port=1883,
                                 user=None,
                                 passwd=None,
                                 brokerFeedback='/vegehub_status/',
                                 brokerSetting='/vegehub_config/'):
        '''
        setup local mqtt connection to broker for feedback
        '''
        if not broker:
            return None
        try:
            # connect to broker
            self.mqttc = paho.Client()
            # Assign event callbacks
            self.mqttc.on_connect = self.broker_on_connect
            self.mqttc.on_disconnect = self.broker_on_disconnect
            self.mqttc.on_message = self.broker_on_message
            if user and passwd:
                self.mqttc.username_pw_set(user, passwd)
            self.brokerFeedback = brokerFeedback
            self.brokerSetting = brokerSetting
            self.mqttc.connect(broker, port, 60)
            self.mqttc.loop_start()
        except socket.error:
            self.log.error("Unable to connect to MQTT Broker")
            self.mqttc = None
        return self.mqttc
        
    def broker_on_connect(self, client, userdata, flags, rc):
        self.log.debug("MQTT Broker Connected with result code " + str(rc))
        if rc == 0:
            client.subscribe('{}#'.format(self.brokerSetting))

    def broker_on_disconnect(self, mosq, obj, rc):
        self.log.debug("MQTT Broker disconnected")
        
    def broker_on_message(self, mosq, obj, msg):
        # receive commands and settings from broker
        target = msg.topic.replace(self.brokerSetting,'').split('/')
        payload = msg.payload.decode("utf-8")
        if not len(target):
            return
        vegehub = target[0] #mac address
        if payload == 'get_config':
            self.decode_topics(self.settings)
        elif payload == 'refresh_config':
            if vegehub in self.settings.keys():
                self.settings[vegehub] = {}
                self.log.info('erased settings for {}, waiting for update'.format(vegehub))
            else:
                self.log.warning('No settings for Vegehub {} found'.format(vegehub))
        elif vegehub in self.settings.keys():
            if self.update_settings(target, payload):
                self.settings[vegehub]['who_updated'] = 2
                self.settings[vegehub]["updated"] = self.now()
                self.log.info('settings pending update: {}: {}'.format(target[-1], payload))
                self.log.debug('settings pending update: {}'.format(pprint(self.settings)))
            else:
                self.log.warning('Settings not updated, {} not found in settings'.format(target))
        else:
            self.log.warning('Vegehub {} settings not found'.format(vegehub))
            
    def update_settings(self, keys, value, settings=None):
        '''
        update settings with keys list to value
        returns True if updated, False if setting not found
        '''
        try:
            if not settings:
                settings = self.settings[keys.pop(0)]   #key[0] is mac address
                value = self.get_value(value)
                
            if not isinstance(settings[keys[0]], (dict, list)):
                settings[keys[0]] = value
                return True
            elif isinstance(settings[keys[0]], dict):
                settings[keys[0]][keys[1]] = value
                return True
            elif isinstance(settings[keys[0]], list):   #all lists are lists of dicts
                for i in settings[keys[0]]:
                    if isinstance(i, dict):             #should be all lists are lists of dicts
                        if self.get_slot(i) == self.get_value(keys[1]):
                            return self.update_settings(keys[2:], value, i)
                    else:
                        return self.update_settings(keys[1:], value, i)
        except Exception as e:
            self.log.error(e)
        return False
    
    def get_value(self, value):
        '''
        converts string from MQTT to int, float or returns string
        '''
        try:
            v = int(value) if value.isdigit() else float(value)
        except:
            return value
        return v
        
    def get_slot(self, i):
        return i.get('slot', i.get('idx', i.get('actuator_slot')))
        
    def get_mac(self, key):
        '''
        tries to find mac address in self.settings from key value, which should be
        api_key, id, ip address or name
        if mac can't be found returns the hub ip address (of last connected hub)
        '''
        for mac, v in self.settings.items():
            id = [x for x in ['api_key', 'id'] if v.get(x) == key]
            if id or v['hub'].get('current_ip_addr') == key or v['hub'].get('name') == key:
                return mac
        return self.remote_host
                       
    def decode_topics(self, settings, prefix=None):
        '''
        decode json data dict, and publish as individual topics to
        brokerFeedback/topic the keys are concatenated with _ to make one unique
        topic name strings are expressly converted to strings to avoid unicode
        representations
        '''
        for k, v in settings.items():
            if isinstance(v, dict):
                if prefix is None:
                    self.decode_topics(v, k)
                else:
                    self.decode_topics(v, '{}_{}'.format(prefix, k))
            else:
                if isinstance(v, list):
                    for i in v:
                        if isinstance(i, dict):
                            self.decode_topics(i, '{}_{}_{}'.format(prefix, k, self.get_slot(i)))
                        else:
                            self.decode_topics(i, '{}_{}'.format(prefix, k))
                            
            if prefix is not None:
                k = '{}_{}'.format(prefix, k)        
            self.publish(k, str(v))
    
    def get_id(self, i):
        '''
        Gets unique id from dict i, tries api_key, id
        '''
        id = [i.get(x) for x in ['api_key', 'id'] if i.get(x) ]
        return id[0] if id else None
        
    def get_channel_id(self, data):
        '''
        gets hub id from data update
        V3.0 hubs used to send 'channel_id', but since FW V3.9 now only sends 'key' which is 'api_key'
        if neither of these have a value, try to get the MAC address or name from hub ip address
        if all else fails return hub ip address
        '''
        id = [data.get(x) for x in ['channel_id', 'key'] if data.get(x) ]
        if not id:
            mac = self.get_mac(self.remote_host)
            if mac and mac != self.remote_host:
                name = self.settings[mac]['hub']['name']
                return name if name else mac
        return id[0] if id else self.remote_host
    
    def now(self):
        '''
        returns UTC time in default javascript iso format as string
        '''
        #return dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')   #"2021-05-25T15:20:52Z" UTC format
        return dt.datetime.utcnow().isoformat()[:-3]+'Z'    #UTC format 2021-05-26T20:05:35.392Z
        
    def start_web(self):
        routes = web.RouteTableDef()
            
        @routes.post('/')
        async def recieved_update(request):
            self.remote_host = request.remote
            if request.can_read_body:
                post_json = await request.json()
                self.log.info('received: {}'.format(post_json))
                self.log.debug(pprint(post_json))
                await self.process_update(post_json)
                who_updated, mac = await self.have_settings(post_json)
                resp = {'who_updated' : who_updated}
                if who_updated == 2:
                    self.log.info('Sending updated settings:')
                    resp.update(self.settings[mac])
                self.log.info('sending response')
                self.log.debug(pprint(resp))
                return web.Response(body=json.dumps(resp), content_type='application/json')
            raise web.HTTPBadRequest(reason='bad api call {}'.format(str(request.rel_url)))
            
        @routes.post('/configin')
        async def recieved_config_update(request):
            if request.can_read_body:
                post_json = await request.json()
                self.log.info('received configuration update')
                self.log.debug(pprint(post_json))
                await self.save_settings(post_json)
                return web.Response(text='{"who_updated" : 1}', content_type='application/json')
            raise web.HTTPBadRequest(reason='bad api call {}'.format(str(request.rel_url)))

        self.app = web.Application()
        self.app.add_routes(routes)
        for webport in self.webport:
            self.log.info('starting api WEB Server V{} on port {}'.format(self.__version__, webport))
            self.web_task.append(self.loop.create_task(web._run_app(self.app, host='0.0.0.0', port=webport, print=None, access_log=self.log)))
        
    async def have_settings(self, post_json):
        '''
        data updates from hub V3.9 only contain api_key (as 'key')
        not 'channel_id' or 'mac' address, so look up 'api_key' in settings
        to see if we have received a configuration update from the hub
        if so, return 'who_updated' and 'mac' address
        '''
        key = post_json.get('key')
        for mac, settings in self.settings.items():
            for k, v in settings.items():
                if k == 'api_key'and v == key:
                    return settings["who_updated"], mac
        return 0, None
    
    async def save_settings(self, post_json):
        mac = post_json['mac']
        if mac in self.settings.keys():
            if self.settings[mac] == post_json:
                self.log.info('settings are up to date')
            else:
                self.log.info('settings updated')
        else:
            self.log.info('New vegehub {} found'.format(mac))
        self.settings[mac] = post_json
        self.decode_topics(self.settings)
        self.write_settings()
                
    def write_settings(self):
        with open(self.config_file, 'w') as f:
            f.write(pprint(self.settings))
            
    def load_settings(self):
        try:
            with open(self.config_file, 'r') as f:
                settings = json.loads(f.read())
            return settings
        except Exception as e:
            self.log.warning('Could not load settings: {}'.format(e))
        return {}
    
    async def process_update(self, post_json):
        '''
        override this to process your own data in a super class
        '''
        channel = self.get_channel_id(post_json)
        if 'updates' in post_json.keys():
            for update in post_json['updates']:
                for k, v in update.items():
                    self.publish(k, v, channel)
        
    def publish(self, topic, msg, hub_id=None):
        if self.mqttc:
            topic = '{}{}{}'.format(self.brokerFeedback, '{}/'.format(hub_id) if hub_id else '', topic)
            self.mqttc.publish(topic, msg)    
        
    async def cancel(self):
        '''
        shutdown web server
        '''
        if self.mqttc:
            self.mqttc.loop_stop()
        if self.app:
            await self.app.shutdown()
            await self.app.cleanup()
        if self.web_task:
            for webtask in self.webtask:
                if not web_task.done():
                    web_task.cancel()    

            
class gateserver(vegehubserver):
    '''
    Configuration (V3.0 Firmware)
    sensor - red is ground, black is signal, green unused. Sensor is NO when gate is closed. ie 0 = OPEN 3.3V = CLOSED
    vegehub is on http://192.168.100.126 (new is on 127)
    server is 192.168.100.113:8060
    send battery info checked.
    channel is 'gate'
    api key is 'gate'
    channel 1  used for ground only , leave in sample mode
    channel 2 is gate periodic, sample mode, send full report
    channel 3 is gate interrupt, trigger both, send full report DISABLED (or the channel does not work V3.0 f/w), continual power off, pull up resistor enabled
    channel 4 is light sensor   set periodic, send full report, power sensor 1 second before report
    
    test unit:
    Configuration (V3.9 Firmware)
    sensor - brown is ground, blue is signal. Sensor is NO when gate is closed. ie 0 = OPEN 3.3V = CLOSED
    vegehub is on http://192.168.100.127
    server is 192.168.100.113:8061
    no "send battry info" checkbox (always sent?)
    channel is 'test'
    api key is 'test'
    channel 1 is gate interrupt, trigger both, send full report DISABLED (or the channel does not work V3.9 f/w), continual power off, pull up resistor enabled
    channel 2 is gate periodic, sample mode, send full report, pullup disabled
    channel 3 unused leave in sample mode
    channel 4 is light sensor set periodic, send full report, power sensor 1 second before report
    '''

    def __init__(self, webport=None, log=None, arg=None):
        if log:
            self.log = log
        else:
            self.log = logging.getLogger("Vegehub.api.{}".format(__class__.__name__))
        self.arg = arg
        self.hub_id = None
        self.tz_offset = dt.datetime.now() - dt.datetime.utcnow()
        self.IR_offset = 0.67   #offset created by IR lights from camera
        super().__init__(webport, self.log, arg)
        
    async def process_update(self, post_json):
        '''
        Override vegehubserver method
        '''
        self.hub_id = self.get_channel_id(post_json)
        self.publish("status", "online")
        updates = post_json.get('updates')
        if updates:
            self.decode_gate(updates)   #process all updates for gate, as we are only interested in the first and last update
            for update in updates:
                self.decode_light(update)
                self.decode_battery(update)
        else:
            self.log.warning('No Update in POST:\n{}'.format(pprint(post_json)))
            
    def publish(self, topic, msg):
        super().publish(topic, msg, self.hub_id)
   
    def battery_percent(self,bat_volt):
        '''
        Calculate battery percentage from battery voltage
        bat_volt is a float in V eg 9.00 V
        Max voltage is dependant on supply voltage
        which is 5.5V to 12V. Usually supplied by 9V battery pack
        or 12V external supply.
        We guess at the max voltage based on batt_volt
        '''
        Vmax = 9.0 if bat_volt <= 9.5 else 12.0    
        Vmin = 5.5
        bat_percent = int(((bat_volt - Vmin)/ (Vmax-Vmin))* 100)
        return str(min(100,max(0,bat_percent)))
        
    def format_date_time(self,date_string):
        date_time =  dt.datetime.now() if not date_string else dt.datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S')+self.tz_offset
        return date_time.isoformat()
        
    def calculate_lux(self, volts):
        # Note, picks up IR from camera, 0.67V - 1V
        #This is with camera IR on.
        #1.2 V = 20 lux
        #0.77V = 5 lux
        IR_offset = self.IR_offset
        lux = (math.pow(10,max(volts - IR_offset, 0))-1) * 10    #sort of - not really
        return round(lux,2)
        
    def decode_gate(self, updates):
        '''
        Process all updates for gate, we are only interested in the last update for the gate
        We can ignore the rest at we only want the final state.
        Sensor is NO when gate is closed. ie 0 = OPEN 3.3V = CLOSED
        With V 3.9FW, the way the sensors trigger is:
        Initial trigger gets reported immediately.
        Subesquent triggers are stored, and finally sent about 20 seconds later as a series
        (I assume this is to prevent rapid connections/disconnections)
        This means we are only interested in the last gate event in the update - as this is the current State
        '''
        if not isinstance(updates, list): #make sure it's a list...
            updates = [updates]
        gate_state = None
        for update in updates:
            gate = None
            gate1 = update.get('field1')  #interrupt triggered
            gate2 = update.get('field2')  #periodic update
            gate3 = update.get('field3')  #interrupt triggered (replacement for channel 1 as that now seems to be dodgy)
            ts = self.format_date_time(update.get('created_at'))
            
            if gate1 is not None:
                source='sensor'
                gate = gate1
            if gate3 is not None:
                source='sensor'
                gate = gate3
            if gate2 is not None:
                source='periodic'
                gate = gate2
            
            if gate is not None:
                gate_state= ('CLOSED' if gate > 1.0 else 'OPEN', source, ts)
        
        if gate_state:
            self.log.info('Gate is {}({}) at:{}'.format(gate_state[0],gate_state[1],gate_state[2]))    
            self.publish(gate_state[1]+"/gate", gate_state[0])
            self.publish(gate_state[1]+"/gate_last_update", gate_state[2])
            
    def decode_light(self, update):
        light = update.get('field4')
        ts = self.format_date_time(update.get('created_at'))
        IR_offset = self.IR_offset
        if light is not None: #note, there is 0.67 - 1V offset due to IR lights at night
            light = min(light, 3.3) #limit max value
            if  light > 3.1:
                bright = 'Very Bright'
            elif  light > 2.7:
                bright = 'Bright'
            elif  light > 1.17:
                bright = 'Daylight'
            elif  light > IR_offset:
                bright = 'Dusk'
            elif  light <= IR_offset:
                bright = 'Dark'
            lux = self.calculate_lux(light)
            self.log.info('{} ({}V, {}lux) at:{}'.format(bright, light, lux, ts))
            self.publish("light", bright)
            self.publish("light_value", light)
            self.publish("light_lux", lux)
            self.publish("light_last_update", ts)
        
    def decode_battery(self, update):
        battery = update.get('field5')
        ts = self.format_date_time(update.get('created_at'))
        if battery is not None:
            bat_percent = self.battery_percent(battery)
            self.log.info('battery is: {}% at:{}'.format(bat_percent,ts))
            self.publish("battery_volts", battery)
            self.publish("battery", bat_percent)
            self.publish("battery_last_update", ts)
 
def pprint(obj):
    """Pretty JSON dump of an object."""
    return json.dumps(obj, sort_keys=True, indent=2, separators=(',', ': ')) 
            
def sigterm_handler(signal, frame):
    log.info('Received SIGTERM signal')
    sys.exit(0)

def setup_logger(logger_name, log_file, level=logging.DEBUG, console=False):
    try: 
        l = logging.getLogger(logger_name)
        formatter = logging.Formatter('[%(levelname)1.1s %(asctime)s] (%(name)-5s) %(message)s')
        if log_file is not None:
            fileHandler = logging.handlers.RotatingFileHandler(log_file, mode='a', maxBytes=2000000, backupCount=5)
            fileHandler.setFormatter(formatter)
        if console == True:
            formatter = logging.Formatter('[%(levelname)1.1s %(name)-5s] %(message)s')
            streamHandler = logging.StreamHandler()
            streamHandler.setFormatter(formatter)

        l.setLevel(level)
        if log_file is not None:
            l.addHandler(fileHandler)
        if console == True:
          l.addHandler(streamHandler)
             
    except Exception as e:
        print("Error in Logging setup: %s - do you have permission to write the log file??" % e)
        sys.exit(1)
    
def main():
    global log
    import argparse
    parser = argparse.ArgumentParser(description='Message handler for Vegehub')
    parser.add_argument('server_port', nargs='*', action="store", type=int, default=8060, help='http server port list (default: %(default)s)')
    parser.add_argument('-cf','--config', action="store", default='config.json', help='config file (used for all configurations) (default: %(default)s)')
    #parser.add_argument('-cid','--client_id', action="store", default=None, help='optional MQTT CLIENT ID (default: %(default)s)')
    parser.add_argument('-b','--broker', action="store", default=None, help='mqtt broker to publish sensor data to. (default: %(default)s)')
    parser.add_argument('-p','--port', action="store", type=int, default=1883, help='mqtt broker port (default: %(default)s)')
    parser.add_argument('-u','--user', action="store", default=None, help='mqtt broker username. (default: %(default)s)')
    parser.add_argument('-pw','--password', action="store", default=None, help='mqtt broker password. (default: %(default)s)')
    parser.add_argument('-pt','--pub_topic', action="store",default='/vegehub_status/', help='topic to publish vegehub data to. (default: %(default)s)')
    parser.add_argument('-st','--sub_topic', action="store",default='/vegehub_config/', help='topic to send vegehub config to. (default: %(default)s)')
    parser.add_argument('-l','--log', action="store",default="None", help='log file. (default: %(default)s)')
    parser.add_argument('-D','--debug', action='store_true', help='debug mode', default = False)
    parser.add_argument('-V','--version', action='version',version='%(prog)s {version}'.format(version=__VERSION__))

    arg = parser.parse_args()
    
    if arg.debug:
      log_level = logging.DEBUG
    else:
      log_level = logging.INFO
    
    #setup logging
    if arg.log == 'None':
        log_file = None
    else:
        log_file=os.path.expanduser(arg.log)
    setup_logger('Vegehub',log_file,level=log_level,console=True)
    
    log = logging.getLogger('Vegehub')
    
    log.debug('Debug mode')
    
    log.info("Python Version: %s" % sys.version.replace('\n',''))
    log.info("Vegehub Server Version: %s" % __version__)
    
    #register signal handler
    signal.signal(signal.SIGTERM, sigterm_handler)

    broker = arg.broker
    port = arg.port
    user = arg.user
    password = arg.password
    
    if not HAVE_MQTT:
        arg.broker = None

    try:
        loop = asyncio.get_event_loop()
        web = gateserver(webport=arg.server_port, arg=arg)
        loop.run_forever()
        
    except (KeyboardInterrupt, SystemExit):
        log.info("System exit Received - Exiting program")
        
    finally:
        pass
        
if __name__ == '__main__':
    main()
        