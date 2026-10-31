"""Exercise real protocol adapters against local simulated OPC UA and MQTT sources."""
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import socket
import sys
from uuid import uuid4
import httpx
from asyncua import Server
from amqtt.broker import Broker
from amqtt.client import MQTTClient

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output'/'qa';OUT.mkdir(parents=True,exist_ok=True)
BASE='http://127.0.0.1:8001'
def port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

async def main():
    async with httpx.AsyncClient(timeout=20) as http:
        opc_id='OPCUA-DEMO-'+uuid4().hex[:6]
        await http.post(BASE+'/api/machines',json={'id':opc_id,'name':'Local OPC UA adapter test','location':'Simulated local protocol server'})
        server=Server();await server.init();endpoint=f'opc.tcp://127.0.0.1:{port()}/mechora/'
        server.set_endpoint(endpoint);index=await server.register_namespace('mechora-test')
        machine=await server.nodes.objects.add_object(index,'DemoMachine');mapping={}
        for field,value in {'air_temperature':300.,'process_temperature':310.,'rotational_speed':1500.,'torque':40.,'tool_wear':100.}.items():
            node=await machine.add_variable(index,field,value);mapping[field]=node.nodeid.to_string()
        map_file=OUT/'opcua-test-nodes.json';map_file.write_text(json.dumps(mapping),encoding='utf-8')
        async with server:
            proc=await asyncio.create_subprocess_exec(sys.executable,str(ROOT/'scripts'/'connector.py'),'--base-url',BASE,'opcua','--url',endpoint,'--nodes',str(map_file),'--machine-id',opc_id,'--count','2','--interval','.1',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            stdout,stderr=await asyncio.wait_for(proc.communicate(),30)
            assert proc.returncode==0,(stdout.decode(),stderr.decode())
        readings=(await http.get(BASE+f'/machines/{opc_id}/readings'.replace('/machines','/api/machines'))).json()
        assert readings['total']==2,readings
        mqtt_id='MQTT-DEMO-'+uuid4().hex[:6]
        await http.post(BASE+'/api/machines',json={'id':mqtt_id,'name':'Local MQTT adapter test','location':'Simulated local broker'})
        mqtt_port=port();broker=Broker({'listeners':{'default':{'type':'tcp','bind':f'127.0.0.1:{mqtt_port}'}},'plugins':{'amqtt.plugins.authentication.AnonymousAuthPlugin':{'allow_anonymous':True}}})
        await broker.start()
        proc=await asyncio.create_subprocess_exec(sys.executable,str(ROOT/'scripts'/'connector.py'),'--base-url',BASE,'mqtt','--host','127.0.0.1','--port',str(mqtt_port),'--topic','mechora/test',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        publisher=MQTTClient()
        try:
            await publisher.connect(f'mqtt://127.0.0.1:{mqtt_port}/')
            await asyncio.sleep(1)
            deadline=asyncio.get_running_loop().time()+10
            payload={'machine_id':mqtt_id,'observed_at':datetime.now(timezone.utc).isoformat(),'type':'M','air_temperature':300,'process_temperature':310,'rotational_speed':1500,'torque':40,'tool_wear':100,'external_id':'mqtt-test-1'}
            while asyncio.get_running_loop().time()<deadline:
                await publisher.publish('mechora/test',json.dumps(payload).encode(),qos=1)
                await asyncio.sleep(.3)
                response=await http.get(BASE+f'/api/machines/{mqtt_id}/readings')
                if response.status_code==200 and response.json()['total']==1:break
            assert response.status_code==200 and response.json()['total']==1,response.text
        finally:
            proc.terminate();await proc.communicate();await publisher.disconnect();await broker.shutdown()
        print(json.dumps({'status':'passed','checks':['OPC UA adapter read and persisted two measurements','MQTT adapter received and persisted a published reading','duplicate MQTT deliveries remain one saved observation'],'sources':'Local simulated protocol servers; no physical factory connection claimed.'}))

if __name__=='__main__':asyncio.run(main())
