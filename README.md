# kube-gw

This is an experiment in running kubernetes directly on the spine or border leaf of a modern [pure-l3 clos datacenter network](https://datatracker.ietf.org/doc/html/rfc7938#section-3.2) - the purpose of which; to optimize north/south traffic flow and enable simple load balancing through tighter coupling of the L3 fabric and k8s control plane.

With a system like metallb in l2 mode, it is not only possible - but likely that traffic initially ends up on a node that doesn't contain the target pods, where it is then forwarded by kube-proxy to its correct destination.  In l3 mode this is alleviated to some degree with `ExternalTrafficPolicy=local`, but then the system is sensitive to the stability of your routers' ecmp hashing.  Linux does not yet feature 'stable' ecmp.

There is also the matter of ingress controllers.  In the worst case - traffic may make its first hop to a Service on a random node, second hop to a node with an ingress controller pod, and third hop to a pod in the deployment.  This can be alleviated to some degree by deploying ingress controllers as a daemonset and nodeport with, again, `ExternalTrafficPolicy=local`, but this is still not ideal - this is accidental complexity.

By getting traffic into the kubneretes network sooner rather than later, we allow kube-proxy to make the load balancing decisions; eliminating these extra network hops and resulting in an overall more correct system.  With careful taints and tolerations, we can solve the ingress case as well, by simply running our ingress controllers directly on our routers.

While I am running these experiments on what is effectively e-waste running linux; I see no practical reason this approach couldnt be replicated with proper whitebox x86 ONIE datacenter swtches from the likes of Mellenox/Nvidia, Supermicro, etc.

---

We do this by abusing bgp's `redistribute connected` option - simply assigning /32 addresses to the loopback interfaces of the kubernetes routers.  This is admittedly a bit of a hack, but it provides an interface that is easy to inspect and reason about (the more correct way to do this would be to inject routes directly into bgp).  The included python program watches kubernetes' ClusterIP Services, gathers a list of ExternalIPs, and sychronizes the network as needed.

Why ClusterIP and not LoadBalancer?  A bit of kubernetes trivia - service type LoadBalancer is actually a superset containing NodePort and ClusterIP, implementing the functionality of both.  A service of type ClusterIP with an ExternalIP installs the same iptables or ipvs virtual-ip traffic intercept rules that a LoadBalancer would, but without the nodeport.  Less open ports is certainly a win.

You may have noticed this implementation doesn't address the fact we have multiple spine routers acting as kube-gateways - this is intentional.  All participating kube-gw nodes will assume the same IPs, resulting in anycast routing.  Through this mechanism, we will get equal-cost-multipathing to the loadbalancers themselves - which if running kube-proxy in ipvs mode with source hashing (`--proxy-mode: ipvs`, `--ipvs-scheduler: sh`), should make the same forwarding decisions as one-another (source needed).

## demo

```
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
  labels:
    name: nginx
spec:
  selector:
    matchLabels:
      name: nginx
  replicas: 4
  template:
    metadata:
      labels:
        name: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:latest

---

apiVersion: v1
kind: Service
metadata:
  name: nginx
  labels:
    name: nginx
spec:
  type: ClusterIP
  externalIPs:
    - 10.0.100.30
    - 10.0.100.31
  ports:
    - port: 80
      name: port1
    - port: 81
      targetPort: 80
      name: port2
  selector:
    name: nginx
```

```
kubectl apply -f nginx.yml
deployment.apps/nginx created
service/nginx created
```

addresses get provisioned:

```
INFO:root:using network 10.0.100.0/24
INFO:root:using interface lo
INFO:root:assuming address 10.0.100.30
INFO:root:assuming address 10.0.100.31
```

```
ip ad show dev lo
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet 10.0.0.20/32 scope global lo
       valid_lft forever preferred_lft forever
    inet 10.0.100.30/32 scope global lo
       valid_lft forever preferred_lft forever
    inet 10.0.100.31/32 scope global lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host noprefixroute 
       valid_lft forever preferred_lft forever
```

kube-gw router is 10.0.0.20, pods are on 10.0.0.21 and 10.0.0.22.

```
# kubectl get pods -o wide
NAME                     READY   STATUS    RESTARTS   AGE     IP             NODE        NOMINATED NODE   READINESS GATES
nginx-689bc475b8-hdlcv   1/1     Running   0          2m10s   10.1.80.176    nve-27e21   <none>           <none>
nginx-689bc475b8-2jxb2   1/1     Running   0          2m10s   10.1.128.214   nve-6e38e   <none>           <none>
nginx-689bc475b8-5csrq   1/1     Running   0          2m10s   10.1.128.198   nve-6e38e   <none>           <none>
nginx-689bc475b8-2gt7l   1/1     Running   0          2m10s   10.1.80.180    nve-27e21   <none>           <none>
```

Heres a perspective from outside the cluster:

```
~$ nmap 10.0.0.20
Starting Nmap 7.80 ( https://nmap.org ) at 2023-08-21 23:28 CDT
Nmap scan report for 10.0.0.20
Host is up (0.0012s latency).
Not shown: 998 closed ports
PORT    STATE SERVICE
22/tcp  open  ssh
179/tcp open  bgp

Nmap done: 1 IP address (1 host up) scanned in 0.04 seconds
~$ nmap 10.0.0.21
Starting Nmap 7.80 ( https://nmap.org ) at 2023-08-21 23:29 CDT
Nmap scan report for 10.0.0.21
Host is up (0.00097s latency).
Not shown: 998 closed ports
PORT    STATE SERVICE
22/tcp  open  ssh
179/tcp open  bgp

~$ nmap 10.0.100.30
Starting Nmap 7.80 ( https://nmap.org ) at 2023-08-21 23:29 CDT
Nmap scan report for 10.0.100.30
Host is up (0.0019s latency).
Not shown: 996 closed ports
PORT    STATE SERVICE
22/tcp  open  ssh
80/tcp  open  http
81/tcp  open  hosts2-ns
179/tcp open  bgp

Nmap done: 1 IP address (1 host up) scanned in 0.05 seconds
```

Our service is available on ports 80 and 81 on both desired IPs, and not on host IP:

```
# curl -s 10.0.100.31 | grep title
<title>Welcome to nginx!</title>
# curl -s 10.0.100.30:81 | grep title
<title>Welcome to nginx!</title>
# curl 10.0.0.21
curl: (7) Failed to connect to 10.0.0.21 port 80 after 0 ms: Couldn't connect to server
```
