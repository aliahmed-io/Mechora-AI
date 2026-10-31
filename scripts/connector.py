"""Forward CSV, MQTT, or OPC UA measurements into Mechora's saved-reading API."""
import argparse
import asyncio
import csv
from datetime import datetime,timezone
import json
from pathlib import Path
import time
import httpx

MAPPING={'Type':'type','Air temperature [K]':'air_temperature','Process temperature [K]':'process_temperature','Rotational speed [rpm]':'rotational_speed','Torque [Nm]':'torque','Tool wear [min]':'tool_wear','Machine ID':'machine_id','Timestamp':'observed_at','timestamp':'observed_at'}
REQUIRED=['machine_id','observed_at','type','air_temperature','process_temperature','rotational_speed','torque','tool_wear']

def normalize(payload,unit='K',machine=None):
    if unit=='C' and any('[K]' in str(key) for key in payload):raise ValueError('Do not use Celsius conversion with columns explicitly labeled [K]. Use short field names for Celsius data.')
    row={MAPPING.get(key,key):value for key,value in payload.items()}
    if machine:row['machine_id']=machine
    missing=[c for c in REQUIRED if row.get(c) in (None,'')]
    if missing:raise ValueError('Missing connector fields: '+', '.join(missing))
    result={key:row[key] for key in REQUIRED};result['type']=str(result['type']).upper()
    for key in REQUIRED[3:]:result[key]=float(result[key])
    if unit=='C':
        result['air_temperature']+=273.15;result['process_temperature']+=273.15
    if row.get('external_id'):result['external_id']=str(row['external_id'])
    return result

def send(client,base,payload,unit='K',machine=None):
    body=normalize(payload,unit,machine)
    response=client.post(base.rstrip('/')+'/api/ingestion/readings',json=body);response.raise_for_status()
    reading=response.json();print(json.dumps({'machine':reading['machine_id'],'observed_at':reading['observed_at'],'risk':reading['risk'],'probability':reading['probability'],'saved_reading_id':reading['id']}),flush=True)
    return reading

async def opcua(args):
    try:from asyncua import Client
    except ImportError:raise SystemExit('Install backend/requirements-connectors.txt to use OPC UA.')
    mapping=json.loads(Path(args.nodes).read_text(encoding='utf-8'))
    required=['air_temperature','process_temperature','rotational_speed','torque','tool_wear']
    if any(key not in mapping for key in required):raise SystemExit('The node map must include all five numeric measurement fields.')
    async with Client(url=args.url) as connection:
        with httpx.Client(timeout=30) as http:
            count=0
            while args.count==0 or count<args.count:
                values={key:await connection.get_node(mapping[key]).read_value() for key in required}
                values.update(machine_id=args.machine_id,observed_at=datetime.now(timezone.utc).isoformat(),type=await connection.get_node(mapping['type']).read_value() if 'type' in mapping else args.product_type)
                await asyncio.to_thread(send,http,args.base_url,values,args.temperature_unit)
                count+=1
                if args.count==0 or count<args.count:await asyncio.sleep(args.interval)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8001')
    parser.add_argument('--temperature-unit',choices=['K','C'],default='K')
    sub=parser.add_subparsers(dest='mode',required=True)
    csv_parser=sub.add_parser('csv',help='Forward timestamped recorded measurements; does not invent missing times.')
    csv_parser.add_argument('path');csv_parser.add_argument('--machine-id');csv_parser.add_argument('--interval',type=float,default=0)
    mqtt_parser=sub.add_parser('mqtt',help='Subscribe to JSON readings from an MQTT broker.')
    mqtt_parser.add_argument('--host',required=True);mqtt_parser.add_argument('--port',type=int,default=1883);mqtt_parser.add_argument('--topic',required=True)
    opc_parser=sub.add_parser('opcua',help='Read actual measurements from a configured OPC UA server.')
    opc_parser.add_argument('--url',required=True);opc_parser.add_argument('--nodes',required=True);opc_parser.add_argument('--machine-id',required=True)
    opc_parser.add_argument('--product-type',choices=['L','M','H'],default='M');opc_parser.add_argument('--interval',type=float,default=2);opc_parser.add_argument('--count',type=int,default=0)
    args=parser.parse_args()
    if getattr(args,'interval',0)<0:parser.error('Interval must be nonnegative.')
    if args.mode=='opcua':return asyncio.run(opcua(args))
    with httpx.Client(timeout=30) as http:
        if args.mode=='csv':
            with open(args.path,encoding='utf-8-sig',newline='') as source:
                for row in csv.DictReader(source):send(http,args.base_url,row,args.temperature_unit,args.machine_id);time.sleep(args.interval)
        else:
            try:import paho.mqtt.client as mqtt
            except ImportError:raise SystemExit('Install backend/requirements-connectors.txt to use MQTT.')
            client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            def connected(client,userdata,flags,reason_code,properties):
                if reason_code==0:client.subscribe(args.topic,qos=1)
                else:print('Broker connection failed:',reason_code,flush=True)
            def received(client,userdata,message):
                try:send(http,args.base_url,json.loads(message.payload.decode('utf-8')),args.temperature_unit)
                except Exception as exc:print('Reading rejected:',str(exc),flush=True)
            client.on_connect=connected;client.on_message=received;client.connect(args.host,args.port);client.loop_forever()

if __name__=='__main__':main()
