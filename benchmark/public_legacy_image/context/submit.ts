// Package only this script; inject the capability via authorized launch SSH/stdin into a protected file, never the image.
// stdin is an existing immutable delivery bundle, never a native command.
import {dependencies,privateJSON,capability,channel,bootstrapOptions,MAX,sha} from './common.ts';
process.on('uncaughtException',()=>{console.error('benchmark submit refused');process.exit(2);});
process.on('unhandledRejection',()=>{console.error('benchmark submit refused');process.exit(2);});
const config=privateJSON(process.argv[2]);const cap=capability(config.url);const timeout=Number(process.argv[3]||10000);const key=process.argv[4];
if(!Number.isFinite(timeout)||timeout<1||timeout>30000||!/^[a-f0-9]{64}$/.test(key))throw Error('submit limits');
const {Swarm,DHT}=dependencies();let swarm:any,complete=false;const timer=setTimeout(()=>{swarm?.destroy();process.exit(1);},timeout);
const parts:Buffer[]=[];let total=0;
for await(const chunk of process.stdin){total+=chunk.length;if(total>MAX)throw Error('bundle too large');parts.push(chunk);}
const body=Buffer.concat(parts);if(!body.length)throw Error('empty bundle');const hash=sha(body);
swarm=new Swarm({...bootstrapOptions(config,DHT),maxPeers:2});swarm.on('error',()=>{});let current:any=null,connections=0;
swarm.on('connection',(socket:any)=>{
 if(complete||++connections>4){socket.destroy();return;}
 const previous=current;current=socket;if(previous)previous.destroy();let offset=0,committed=false;
 channel(socket,cap,false,(m:any,send:any)=>{
  if(m.kind==='authenticated'){send({kind:'begin',key,bytes:body.length,sha256:hash});return;}
  if(m.kind==='next'&&!committed&&m.offset===offset){
   if(offset===body.length){committed=true;send({kind:'commit'});return;}
   const chunk=body.subarray(offset,offset+24576);const start=offset;offset+=chunk.length;send({kind:'chunk',offset:start,data:chunk.toString('base64')});return;
  }
  if(m.kind==='ack'&&committed&&m.key===key&&m.content_sha256===hash&&m.durable===true){
   complete=true;console.log(JSON.stringify({key,content_sha256:hash,durable:true,duplicate:m.duplicate===true}));socket.end();swarm.destroy().then(()=>{clearTimeout(timer);process.exit(0);});return;
  }
  throw Error('unexpected receiver reply');
 });
 socket.on('close',()=>{if(current===socket)current=null;});
});
swarm.join(cap.topic,{server:false,client:true});await swarm.listen();
