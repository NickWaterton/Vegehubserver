#!/usr/bin/env python3
# Author: Nick Waterton <nick.waterton@med.ge.com>
# Description: test MQTT interface to Vegehub Sensor Hub
# NOTE: if the server is down for any length of time (or does not respond), the vegehub will store readings,
# then send them all at once when the server connection is re-establish.
# N Waterton 10th September 2019 V1.0: initial release

from __future__ import print_function

import requests
import json
import datetime

__version__ = __VERSION__ = "1.0.1"
        
def pprint(obj):
    """Pretty JSON dump of an object."""
    return json.dumps(dict(obj), sort_keys=True, indent=2, separators=(',', ': '))

#url = 'http://127.0.0.1:8061/'
url = 'http://192.168.100.113:8061'
data = {"channel_id": "test",
        "updates": [
            {
              "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), #eg "2019-09-10 02:27:24",
              "field2": 2.571,
              "field4": 0.808,
              "field5": 12.49
            }
          ]
        }

r = requests.post(url, json=data, timeout=1.0)
if r.status_code == 200:
    print('SUCCESS:\nreceived: %s\n%s' % (pprint(r.headers), r.text)) 
else:
    print('FAILED: Got Status code: %s' % r.status_code)
