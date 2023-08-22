#!/usr/bin/python3

import os
import netifaces
import logging
import ipaddress
import random
from time import sleep
from kubernetes import client, config


def get_addresses(dev: str) -> list:
    addresses = []

    addrs = netifaces.ifaddresses(dev)
    af_inet_addrs = addrs[netifaces.AF_INET]
    addresses = [i["addr"] for i in af_inet_addrs]

    logging.debug("{} addresses found: {}".format(dev, addresses))

    return addresses


def get_address_state(dev: str, address: str) -> bool:
    """
    determine whether a given address is already assigned
    """
    addresses = get_addresses(dev)

    if address in addresses:
        return True
    else:
        return False


def provision_address(
    dev: str, address: str, netmask: str, initial_ips: list, logging
) -> None:
    """
    assure an address is assigned to a device
    """
    if address not in initial_ips:
        logging.info("assuming address {}".format(address))
        os.system("ip address add {}{} dev {}".format(address, netmask, dev))


def forfeit_address(dev: str, address: str, netmask: str, logging) -> None:
    """
    assure an address is not assigned to a device
    """
    logging.info("forfeiting address {}".format(address))
    os.system("ip address del {}{} dev {}".format(address, netmask, dev))


def get_clusterips(client):
    """
    get a list of services of type LoadBalancer
    """
    api = client.CoreV1Api()
    services = []
    for service in api.list_service_for_all_namespaces().items:
        if service.spec.type == "ClusterIP":
            services.append(service)
    return services


def existing_ips_in_range(addresses, net_range):
    """
    get list of ips in provided range which are currently assigned to an interface
    """
    parsed_addresses = []
    for a in addresses:
        if ipaddress.IPv4Address(a) in ipaddress.IPv4Network(net_range):
            parsed_addresses.append(a)

    return parsed_addresses


if __name__ == "__main__":
    if os.getenv("KUBEGW_DEBUG"):
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if os.getenv("KUBEGW_IN_K8S"):
        config.load_incluster_config()
    else:
        config.load_kube_config()

    network = os.getenv("KUBEGW_NETWORK")
    interface = os.getenv("KUBEGW_INTERFACE")

    logging.info("using network {}".format(network))
    logging.info("using interface {}".format(interface))

    while True:
        sleep(random.randrange(1, 10))

        initial_ips = get_addresses(interface)
        valid_ips = []

        for s in get_clusterips(client):
            if s.spec.external_i_ps:
                for ip in s.spec.external_i_ps:
                    valid_ips.append(ip)

        for ip in valid_ips:
            provision_address(interface, ip, "/32", initial_ips, logging)

        logging.debug("external ips found: {}".format(valid_ips))

        # addresses found within prefix KUBEGW_NETWORK which are unknown by
        # above learning mechanism will be considered invalid and removed.
        invalid_ips = list(
            set(existing_ips_in_range(initial_ips, network)).difference(valid_ips)
        )

        for ip in invalid_ips:
            forfeit_address(interface, ip, "/32", logging)
