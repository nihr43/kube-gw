# kube-gw

This is an experiment in running kubernetes directly on the spine or border leaf of a modern [pure-l3 clos datacenter network](https://datatracker.ietf.org/doc/html/rfc7938#section-3.2) - the purpose of which; to optimize north/south traffic flow and enable simple load balancing through tighter coupling of the L3 fabric and k8s control plane.

With a system like metallb in l2 mode, it is not only possible - but likely that traffic initially ends up on a node that doesn't contain the target pods, where it is then forwarded by kube-proxy to its correct destination.  In l3 mode this is alleviated to some degree with `ExternalTrafficPolicy=local`, but then the system is sensitive to the stability of your routers' ecmp hashing.  Linux does not yet feature 'stable' ecmp.

There is also the matter of ingress controllers.  In the worst case - traffic may make its first hop to a Service on a random node, a second hop to a node with an ingress controller pod, and third hop to a pod in the deployment.  This can be alleviated to some degree by deploying ingress controllers as a daemonset and nodeport with, again, `ExternalTrafficPolicy=local`, but this is still not ideal.

By getting traffic into the kubneretes network sooner rather than later, we allow kube-proxy to make the load balancing decisions; eliminating these extra network hops and resulting in an overall more correct system.  With careful taints and tolerations, we can solve the ingress case as well, by simply running our ingress controllers directly on our routers.

While I am running these experiments on what is effectively e-waste running linux; I see no practical reason this approach couldnt be replicated with proper whitebox x86 ONIE datacenter swtches from the likes of Mellenox/Nvidia, Supermicro, etc.

---
