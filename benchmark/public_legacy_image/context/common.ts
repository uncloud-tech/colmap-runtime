import fs from 'node:fs';
import {createHash,createHmac,timingSafeEqual} from 'node:crypto';
import {createRequire} from 'node:module';
import {EventEmitter} from 'node:events';
export const MAX=8*1024*1024;
export const MAX_CAPABILITY_LIFETIME_MS=24*60*60*1000;
export function capabilityLifetimeMs(seconds:string='3600'){
 if(!/^[0-9]+$/.test(seconds))throw Error('invalid capability lifetime');
 const n=Number(seconds);if(!Number.isSafeInteger(n)||n<60||n>MAX_CAPABILITY_LIFETIME_MS/1000)throw Error('invalid capability lifetime');
 return n*1000;
}
export const sha=(b:any)=>createHash('sha256').update(b).digest('hex');
export function dependencies(){
 const r=createRequire(process.env.BENCH_HOLEPUNCH_DEPS||new URL('./package.json',import.meta.url));
 const Swarm=r('hyperswarm');const d=createRequire(r.resolve('hyperswarm'));
 if(r('hyperswarm/package.json').version!=='4.17.2')throw Error('unqualified transport dependency');
 return {Swarm,DHT:d('hyperdht')};
}
export function privateJSON(path:string){
 const fd=fs.openSync(path,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
 try{const s=fs.fstatSync(fd);if(!s.isFile()||s.uid!==process.getuid?.()||(s.mode&0o077)||s.size>16384)throw Error('restricted config required');return JSON.parse(fs.readFileSync(fd,'utf8'));}finally{fs.closeSync(fd);}
}
export function capability(text:string){
 const u=new URL(text);const p=u.pathname.split('/').filter(Boolean);
 if(u.protocol!=='punch:'||u.hostname!=='benchmark-results'||p.length!==4||u.username||u.password||u.hash)throw Error('benchmark capability only');
 const [topic,token,receiver,run]=p;const expires=Number(u.searchParams.get('expires'));
 if(!/^[a-f0-9]{64}$/.test(topic)||!/^[A-Za-z0-9_-]{43}$/.test(token)||!/^[a-f0-9]{64}$/.test(receiver)||!/^[A-Za-z0-9_-]{1,80}$/.test(run)||!Number.isSafeInteger(expires)||expires<=Date.now()||expires>Date.now()+MAX_CAPABILITY_LIFETIME_MS)throw Error('invalid/expired scope');
 return {topic:Buffer.from(topic,'hex'),token:Buffer.from(token,'base64url'),receiver,run,expires};
}
// Same transport mechanism as Holepunch: encrypted Noise stream + channel-bound
// capability proof. No Pi/team protocol, configuration or code is imported.
export function channel(socket:any,cap:any,receiver:boolean,onMessage:(x:any,send:any)=>void){
 const events=new EventEmitter();let buffer=Buffer.alloc(0),authed=false,wire=0;const deadline=performance.now()+10000;
 const role=socket.isInitiator?'initiator':'responder';
 const proof=(r:string)=>createHmac('sha256',cap.token).update('benchmark-results/v1').update(cap.topic).update(cap.run).update(String(cap.expires)).update(socket.handshakeHash).update(r).digest();
 const send=(value:any)=>{if(performance.now()>=deadline||socket.destroyed)throw Error('connection deadline');const b=Buffer.from(JSON.stringify(value));if(b.length>49152)throw Error('frame quota');const h=Buffer.alloc(4);h.writeUInt32BE(b.length);socket.write(Buffer.concat([h,b]));};
 const timer=setTimeout(()=>socket.destroy(),10000);const authTimer=setTimeout(()=>{if(!authed)socket.destroy();},2000);
 socket.on('error',()=>{});socket.on('close',()=>{clearTimeout(timer);clearTimeout(authTimer);events.emit('closed');});
 socket.on('data',(b:Buffer)=>{
  try{
   if(socket.destroyed)return;
   wire+=b.length;if(performance.now()>=deadline||Date.now()>=cap.expires||wire>(authed?2*MAX:4096))throw Error('connection quota');
   buffer=Buffer.concat([buffer,b]);
   while(buffer.length>=4){const n=buffer.readUInt32BE(0);if(n>(authed?49152:4096))throw Error('frame quota');if(buffer.length<n+4)break;
    const value=JSON.parse(buffer.subarray(4,n+4).toString());buffer=buffer.subarray(n+4);
    if(!authed){
     if(value.kind!=='auth'||!/^[a-f0-9]{64}$/.test(value.proof)||!timingSafeEqual(Buffer.from(value.proof,'hex'),proof(role==='initiator'?'responder':'initiator')))throw Error('auth refused');
     authed=true;clearTimeout(authTimer);events.emit('authenticated');onMessage({kind:'authenticated'},send);
    }else onMessage(value,send);
   }
  }catch{process.stderr.write(JSON.stringify({event:'frame-refused',authenticated:authed})+'\n');socket.destroy();}
 });
 if(!socket.handshakeHash||(!receiver&&socket.remotePublicKey.toString('hex')!==cap.receiver)){socket.destroy();return events;}
 send({kind:'auth',proof:proof(role).toString('hex')});return events;
}
export function bootstrapOptions(config:any,DHT:any){
 if(!config.bootstrap)return {};
 if(!config.bootstrap.every((n:any)=>n.host==='127.0.0.1'&&Number.isInteger(n.port)))throw Error('test bootstrap must be loopback');
 return {dht:new DHT({host:'127.0.0.1',port:[0,0],bootstrap:config.bootstrap})};
}
