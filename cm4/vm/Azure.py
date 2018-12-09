import os
import time
from libcloud.compute.base import NodeAuthSSHKey
from libcloud.compute.drivers.azure_arm import AzureNetwork, AzureSubnet, AzureNodeDriver, Node
from cm4.vm.Cloud import Cloud
from cm4.abstractclass.CloudManagerABC import CloudManagerABC
from libcloud.compute.base import NodeDriver


class AzureProvider(CloudManagerABC, Cloud):

    def __init__(self, config):
        self.credentials = config["cloud"]["azure"]["credentials"]
        self.default = config["cloud"]["azure"]["default"]
        self.driver = AzureDriver(
            tenant_id=self.credentials['AZURE_TENANT_ID'],
            subscription_id=self.credentials['AZURE_SUBSCRIPTION_ID'],
            key=self.credentials['AZURE_APPLICATION_ID'],
            secret=self.credentials['AZURE_SECRET_KEY'],
            region=self.default['region'],
            cm_config=config,
            cm_default=self.default
        )

    def start(self, name):
        """

        :param name:
        :return:
        """
        self.driver.ex_start_node(self.driver._get_node(name))

    def stop(self, name=None):
        """
        Stop a running node. Deallocate resources. VM status will
        be `stopped`.
        :param name:
        """
        self.driver.ex_stop_node(self.driver._get_node(name))

    def info(self, name=None):
        """
        gets the information of a node with a given name

        :param name:
        :return: The dict representing the node including updated status
        """
        return self.driver._get_node(name)

    def suspend(self, name=None):
        """
        suspends the node with the given name

        :param name: the name of the node
        :return: The dict representing the node
        """
        self.driver.ex_stop_node(self.driver._get_node(name), deallocate=False)

    def nodes(self):
        """
        list all nodes id

        :return: an array of dicts representing the nodes
        """
        return self.driver.list_nodes()

    def resume(self, name=None):
        """
        resume the named node

        :param name: the name of the node
        :return: the dict of the node
        """
        self.driver.ex_start_node(self.driver._get_node(name))

    def destroy(self, name=None):
        """
        Destroys the node
        :param name: the name of the node
        :return: the dict of the node
        """
        pass

    def create(self, name=None, image=None, size=None, timeout=360, **kwargs):
        """
        creates a named node
        :return:
        """
        """
        create one node
        """
        return self.driver.create_node(name)

    def rename(self, name=None, destination=None):
        """
        rename a node
        Rename is not directly supported. You have to detach
        the drive, destroy the vm, and recreate a new one with
        the same drive to get a rename effect.

        :param name: the current name
        :param destination: the new name
        :return: the dict with the new name
        """
        raise NotImplementedError("Rename not yet implemented for Azure.")

    def set_public_ip(self, name, public_ip):
        return self.driver.set_public_ip(name, public_ip)

    def remove_public_ip(self, name):
        self.driver.remove_public_ip(name)


class AzureDriver(AzureNodeDriver, NodeDriver):
    """
    Extension for the default Azure ARM driver.
    https://libcloud.readthedocs.io/en/latest/compute/drivers/azure_arm.html
    """
    def __init__(self, tenant_id, subscription_id, key, secret,
                 secure=True, host=None, port=None,
                 api_version=None, region=None, **kwargs):

        self.config = kwargs["cm_config"]
        self.default = kwargs["cm_default"]
        self.subscription_id = subscription_id
        self.resource_group = self.default["resource_group"]
        self.network_name = self.default["network"]
        self.storage_account = self.default["storage_account"]
        self.default_image = None
        self.default_size = None

        super().__init__(tenant_id=tenant_id,
                         subscription_id=subscription_id,
                         key=key, secret=secret,
                         secure=secure,
                         host=host, port=port,
                         api_version=api_version,
                         region=region, **kwargs)

    def suspend(self, name):
        """
        Suspend a running node. Same as `stop`, but resources do not
        deallocate. VM status will be `paused`.
        :param name: The name of the running node.
        """
        self.ex_stop_node(self._get_node(name), deallocate=False)

    def destroy_node(self, node: Node, **kwargs):
        """
        Destroy a node.
        :param node:
        """
        # node = self._get_node(name)
        super().destroy_node(node)
        # Managed volumes are not destroyed by `destroy_node`.
        time.sleep(2)
        print(f"destroying volume for {node.name}")
        self.destroy_volume(self._get_volume(node.name))
        # Libcloud does not delete public IP addresses
        self._ex_delete_public_ip(f"{node.name}-ip")

    def create_node(self, name, **kwargs):
        """
        Create a node
        """
        key_path = self.config["profile"]["key"]["public"]

        with open(os.path.expanduser(key_path), 'r') as fp:
            key = fp.read()

        auth = NodeAuthSSHKey(key)
        image = self._get_default_image()
        size = self._get_default_size()
        nic = self._get_nic(name)

        # Create vm
        new_vm = super().create_node(
            name=name,
            size=size,
            image=image,
            auth=auth,
            ex_nic=nic,
            ex_use_managed_disks=True,
            ex_resource_group=self.resource_group,
            ex_storage_account=self.storage_account
        )

        return new_vm

    def remove_public_ip(self, name):
        """
        Removes a public IP from a VM
        :param name: Node name
        :return:
        """
        # Re-PUT the nic without a public IP to disassociate the IP from the nic
        self._get_nic(name, with_public_ip=False)
        # Delete IP
        self._ex_delete_public_ip(f"{name}-ip")

    def set_public_ip(self, name, ip=None):
        """
        Reset the node with a public IP
        :param name:
        :param ip:
        """
        self._get_nic(name, with_public_ip=True)

    def _get_default_image(self):
        """
        Get an image object corresponding to teh default image id in config.
        :return:
        """
        if self.default_image is None:
            self.default_image = self.get_image(self.default["image"])
        return self.default_image

    def _get_default_size(self):
        """
        Get an size object corresponding to teh default image id in config.
        :return:
        """
        if self.default_size is None:
            sizes = self.list_sizes()
            self.default_size = [s for s in sizes if s.id == self.default["size"]][0]
        return self.default_size

    def _get_nic(self, vm_name, with_public_ip=True):
        """
        Gets a nic associated with the default network/subnet.

        :param vm_name:
        :param with_public_ip:
        """
        # Create a network and default subnet if none exists
        network, subnet = self._get_or_create_network(self.network_name)

        # Create public IP
        if with_public_ip is True:
            public_ip = self.ex_create_public_ip(
                f"{vm_name}-ip",
                resource_group=self.resource_group
            )
        else:
            public_ip = None

        # Create NIC
        nic = self.ex_create_network_interface(
            name=f"{vm_name}-nic",
            subnet=subnet,
            resource_group=self.resource_group,
            public_ip=public_ip
        )

        return nic

    def _get_node(self, name):
        """
        Get an instance of a Node returned by `list` by node name.
        """
        node = [n for n in self.list_nodes() if n.name == name]
        return node[0] if node else None

    def _get_volume(self, volume_id):
        """
        Get the volume named after a created node.
        """
        volume = [v for v in self.list_volumes() if v.name == volume_id]
        return volume[0] if volume else None

    def _get_network(self, network_name):
        """
        Return an instance of a network if it exists.
        """
        net = [n for n in self.ex_list_networks() if n.name == network_name]
        return net[0] if net else None

    def _get_subnet(self, network):
        """
        Returns the first subnet associated with the virtual network.
        Assuming the network was created by this provider, there will
        be only one subnet.

        :param network:
        :return:
        """
        subnet = self.ex_list_subnets(network)[0]
        return subnet

    def _get_or_create_network(self, network_name):
        """
        Create a new network resource if it does not exist or returns
        an existing network resource if it exists.

        If the network exists, we assume that everything else on the network is
        configured and do nothing.

        Otherwise the network is created with a default subnet and a network security
        group that allows inbound SSH traffic.
        """
        existing_network = self._get_network(network_name)

        # Do not recreate an already existing network and subnet.
        if existing_network is not None:
            existing_subnet = self._get_subnet(existing_network)
            return existing_network, existing_subnet

        print(f"Virtual Network {network_name} not found. Creating...")

        network_cidr = "10.0.0.0/16"
        network = self._ex_create_network(name=network_name, cidr=network_cidr)
        time.sleep(1)

        # Create SSH security group
        sec_group_id = self._ex_create_network_security_group(f"{network_name}-ssh-group")

        subnet_name = "default"
        subnet_cidr = "10.0.0.0/16"
        subnet = self._ex_create_subnet(
            name=subnet_name,
            cidr=subnet_cidr,
            network_name=network_name,
            security_group_id=sec_group_id
        )
        time.sleep(1)

        print(f"Created Virtual Network {network_name}.")

        return network, subnet

    def _ex_create_network(self, cidr, name):
        """
        Create a network
        """
        data = {
            "location": self.default_location.id,
            "properties": {
                "addressSpace": {
                    "addressPrefixes": [
                        cidr
                    ]
                }
            }
        }

        action = "/subscriptions/%s/resourceGroups/%s/providers/" \
                 "Microsoft.Network/virtualNetworks/%s" \
                 % (self.subscription_id, self.resource_group, name)

        r = self.connection.request(
            action,
            params={"api-version": "2018-08-01"},
            method="PUT",
            data=data
        )

        return AzureNetwork(
            id=r.object["id"],
            name=r.object["name"],
            location=r.object["location"],
            extra=r.object["properties"]
        )

    def _ex_delete_network(self, name):
        """
        Delete a network
        """
        action = "/subscriptions/%s/resourceGroups/%s/providers/" \
                 "Microsoft.Network/virtualNetworks/%s" \
                 % (self.subscription_id, self.resource_group, name)

        r = self.connection.request(
            action,
            params={"api-version": "2018-08-01"},
            method="DELETE"
        )

        return r

    def _ex_create_subnet(self, cidr, network_name, name, security_group_id=None):
        """
        Create a subnet
        """
        data = {
            "properties": {
                "addressPrefix": cidr,
                "networkSecurityGroup": {
                    "id": security_group_id
                }
            }
        }

        action = "/subscriptions/%s/resourceGroups/%s/providers/" \
                 "Microsoft.Network/virtualNetworks/%s/subnets/%s" \
                 % (self.subscription_id, self.resource_group, network_name, name)

        r = self.connection.request(
            action,
            params={"api-version": "2018-08-01"},
            method="PUT",
            data=data
        )

        return AzureSubnet(
            id=r.object["id"],
            name=r.object["name"],
            extra=r.object["properties"]
        )

    def _ex_delete_public_ip(self, name):
        """
        Delete a public IP
        :param name:
        :return:
        """
        action = "/subscriptions/%s/resourceGroups/%s/providers/" \
                 "Microsoft.Network/publicIPAddresses/%s" \
                 % (self.subscription_id, self.resource_group, name)

        r = self.connection.request(
            action,
            params={"api-version": "2018-08-01"},
            method="DELETE"
        )

        return r

    def _ex_create_network_security_group(self, name):
        """
        An updated version of libcloud's default `ex_create_network_security_group` that
        includes an ssh rule.
        :param name: Name of the network security group to create
        """

        target = "/subscriptions/%s/resourceGroups/%s/" \
                 "providers/Microsoft.Network/networkSecurityGroups/%s" \
                 % (self.subscription_id, self.resource_group, name)
        data = {
            "location": self.default_location.id,
            "properties": {
                "securityRules": [
                    {
                        "name": "SshInbound",
                        "properties": {
                            "protocol": "TCP",
                            "sourceAddressPrefix": "*",
                            "destinationAddressPrefix": "*",
                            "access": "Allow",
                            "destinationPortRange": "22",
                            "sourcePortRange": "*",
                            "priority": 130,
                            "direction": "Inbound"
                        }
                    }
                ]
            }
        }

        r = self.connection.request(
            target,
            params={"api-version": "2016-09-01"},
            data=data,
            method='PUT'
        )

        return r.object["id"]
