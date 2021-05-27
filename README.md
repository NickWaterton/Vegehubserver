# Vegehubserver
Python 3.8 Server to receive Vegehub data, and update configuration remotely

## Features
* Optional MQTT interface
* Receives and stores vegehub configuration locally (V3.9 FW and above)
* Alows updating of Vegehubs configuration remotely (V3.9 FW and above)
* Supports multiple vegehubs/multiple server ports
* Importable class vegeserver
* Asyncronous WebServer (uses asyncio, aiohttp)
* Receives data from all Vegehub FW versions
* Example gateserver() included in file vegeserver2.py

**Note:** Tested on python V 3.8, Ubuntu 20.04 only

## Dependancies
Uses module aiohttp as webserver (pip install aiohttp)

## Command line interface
```
nick@MQTT-Servers-Host:~/Scripts/vegehubserver$ ./vegehubserver2.py -h
usage: vegehubserver2.py [-h] [-cf CONFIG] [-b BROKER] [-p PORT] [-u USER] [-pw PASSWORD] [-pt PUB_TOPIC] [-st SUB_TOPIC]
                         [-l LOG] [-D] [-V]
                         [server_port [server_port ...]]

Message handler for Vegehub

positional arguments:
  server_port           http server port list (default: 8060)

optional arguments:
  -h, --help            show this help message and exit
  -cf CONFIG, --config CONFIG
                        config file (used for all configurations) (default: config.json)
  -b BROKER, --broker BROKER
                        mqtt broker to publish sensor data to. (default: None)
  -p PORT, --port PORT  mqtt broker port (default: 1883)
  -u USER, --user USER  mqtt broker username. (default: None)
  -pw PASSWORD, --password PASSWORD
                        mqtt broker password. (default: None)
  -pt PUB_TOPIC, --pub_topic PUB_TOPIC
                        topic to publish vegehub data to. (default: /vegehub_status/)
  -st SUB_TOPIC, --sub_topic SUB_TOPIC
                        topic to send vegehub config to. (default: /vegehub_config/)
  -l LOG, --log LOG     log file. (default: None)
  -D, --debug           debug mode
  -V, --version         show program's version number and exit
```

## MQTT usage
Data is published to `PUB_TOPIC`, prepended by `api_key`, `channel_id`, `name` or MAC address - depending on what is populated on your Vegehub.  
Saved configurations are published when the server starts or when a new confuration is downloaded from a vegehub (ie if a value is successfully changed).

To change a configuration setting on the vegehub, you would publish:
```
mosquitto_pub -h <broker> -t "SUB_TOPIC/<MAC address>/<setting>/<setting2>" -m <value>
```
For example, to change "report_voltage" to 0 (off) using the default topic, with mac address F8F005AD7A0A:
```
mosquitto_pub -h <broker> -t "/vegehub_config/F8F005AD7A0A/hub/report_voltage" -m 0
```
To change Channel 2 "pull_up" to ON (1):
```
mosquitto_pub -h <broker> -t "/vegehub_config/F8F005AD7A0A/sensors/1/pull_up" -m 1
```
**Note:** Channels are numbered from 0 (web interface numbers from 1)

When the vegehub next wakes up and reports data, it will update it's configuration with the changes.
```
mosquitto_pub -h <broker> -t "/vegehub_config/config" -m get_config
```
Re-publishes the current configuration for all vegehubs.
```
mosquitto_pub -h <broker> -t "/vegehub_config/F8F005AD7A0A" -m refresh_config
```
requests the vegehub at MAC address F8F005AD7A0A to resend it's configuration at the next wake up.

## config.json
The default config file is `config.json`. All settings will be downloaded and stored in this file (V 3.9 FW only).  
Any updates made via the Web interface will be downloaded and stored in this file at the next scheduled wake up (or triggered event).  

The structure of the `config.json` file is:
```
// Vegehub JSON specification V 1.0 (current as of Firmware V3.9 May 2021)
{
    // Send these fields for the request
    "api_key": api_key_str[16],
    "mac": mac_address_str[16],
    "route_key": route_key_str[16],
    // When querying object arrays, create an empty object or array for each item you want filled. 
    // for example "hub":{}, "slots":[] would get the hub object and the slots array.  
    // The server will return the requested objects as the following json objects. 
    // The following request will get all fields: {"api_key": "XXXX","mac": "XXXX","hub":{},"slots":[],"actuators":[],"schedules":[]}
    "updated": updated_timedate_str,  // time of last configuration update to server db.  
    "who_updated": who_updated_int,   // 0: needs updating by hub, 1: hub did last update, 2: web interface did last update.
    "hub": {
        "model": model_str[32], // "VG-HUB1","VG-HUB4","VG-HUB4-RELAY,"VG-SPRINKLER4","VG-SPRINKLER4-LATCH"
        "firmware_version": firmware_version_str,
        "wifi_version": wifi_version_str,
        "utc_offset": utc_offset_int // in seconds. 
        "name": name_str[32], // name of hub
        "sample_period": sample_period_int, // in seconds  (optional)
        "update_period": update_period_int, // in seconds
        "blink_update": blink_update_int, // 0: don't blink, 1: blink
        "report_voltage": report_voltage_int, // 0: don't report, 1: report voltage
        "server_url": server_url_str,
        "static_ip_addr": static_ip_addr,
        "dns": dns,
        "subnet": subnet,
        "gateway": gateway,
        "current_ip_addr": current_ip_addr,	 // the currently assigned IP Address. Only the Hub can set or write this. 
        "power_mode": power_mode_int 	// Hub is connected to- 0: battery power, 1: wall power. 
    },
    "sensors": [ // sensor input channels 
        {
            "slot": slot_int,  // 0 based.
            "mode": mode_int, // 1: sensor, 0: edge
            "warm_up": warm_up_float,	// in seconds.
            "pull_up": pull_up_int,	// 0: no pull up, 1: use pull up.
            "always_power": always_power_int, // 0: power to sensor not always on, 1: always on.
            "update_on_trigger": update_on_trigger_int,  // 0: don't update, 1: update on trigger.
            "edge": edge_int,		// 0: raising, 1: falling, 2: both. 
        },
    ],
    "actuators": [ // relays, valves, pumps, etc.
        {
            "name": name_str[32], 
            "slot": slot_int, // 0 based index of the physical actuator on the board. 
            "type": type_int, 0: undefined, 1: relay, 2: valve, 3: pump. 
            "enabled": enable_int, // 0: disabled, 1: enabled.
            "mode": mode_int, // 0: sensor conditional, 1: web conditional, 2: non-conditional (manual), 3: auto-generated web conditional.
            "url": url_str[256],
            "url_param": url_param_str[256],
            "turn_on": turn_on_int, // 0: OFF, 1: ON
            "time_dependent": time_dependent_int, // 0: not dependent, 1: dependent (optional)
            "start_time": start_time_str, (optional)
            "end_time": end_time_str, (optional)
            "days_of_week": days_of_week_mask_int, // 0: never, 1: sun, 2: mon, 4: tue, etc.  127 every day. (optional)
            "conditions": [
                {
                    "sequence": sequence_int, // operand order. 0 based. 
                    "slot": slot_int,	// sensor channel slot 
                    "operator": operator_int, // 0: greater than, 1: less than, 2: inside, 3: outside, 4: true, 5: false
                    "lower": lower_float,
                    "upper": upper_float,
                    "hysteresis": hysteresis_float,
                    "chain": chain_int  // 0: none, 1: AND, 2: OR
                }
            ]
        },
    ],
    "schedules": [
        {
            "name": name_str[32], 
            "idx": idx_int, // 0 based. index of the schedule 
            "enabled": enabled_bool, // 0: disabled, 1: enabled.
            "mode": mode_int, // 0: calendar, 1: periodic.
            "days_of_week": days_of_week_mask_int, // 0: never, 1: sun, 2: mon, 4: tue, etc.  127 every day. 
            "period": period_int, // time between starts.
            "start_time": start_time_str,
            "actions": [
                {
                    "enabled": enabled_bool, // 0: disabled, 1: enabled.
                    "actuator_slot": actuator_slot_int, // index of the physical actuator on the board. 
                    "duration": duration_int, // on time of actuator in minutes
                }
            ]
        }
    ],
    "web_conditions": [ // length could be less than the number of actuators. 
        {
            "actuator_slot": slot_int, // 0 based indicates the actuator it is tied to. 
            "name": name_str[32], 
            "condition_key": condition_key_str[16], // 0 based. index of the schedule 
        }
    ],
    "schedule_overrides":[
        {
            "id": id_int,						// unique identifier
            "start_time": start_time_str,		// override start time. The zero time of "0000-00-00 00:00:00" means immediate.
            "duration": duration _int,			// (seconds) how long to run actuator
            "actuator_slot": actuator_slot_int, // 0 based index of the actuator. 
            "action_type": action_type_int 		// 1: on, 2: off, 3: cancel. 
        }
    ]
}
```
see https://vegecloud.com/Documentation/HubConfigApi.phtml for protocol details (although the *protocol is currently incorrect* as of May 27th 2021).