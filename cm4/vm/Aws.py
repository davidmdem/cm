from cm4.vm.Cloud import Cloud
from cm4.configuration.config import Config
from cm4.abstractclass.CloudManagerABC import CloudManagerABC

from libcloud.compute.drivers.ec2 import EC2NodeDriver
from libcloud.compute.base import NodeDriver


class AwsProvider(CloudManagerABC, Cloud):

    def __init__(self, config):
        os_config = config["cloud"]["aws"]
        default = os_config.get('default')
        credentials = os_config.get('credentials')
        self.driver = AWSDriver(
            credentials['EC2_ACCESS_ID'],
            credentials['EC2_SECRET_KEY'],
            region=default['region']
        )


class AWSDriver(EC2NodeDriver, NodeDriver):

    def __init__(self, key, secret, region, **kwargs):
        config = Config().data["cloudmesh"]
        self.default = config["cloud"]["aws"]["default"]
        super().__init__(key=key, secret=secret, region=region, **kwargs)

    def ex_stop_node(self, node, deallocate=None):
        super().ex_stop_node(node)

    def create_node(self, name):
        size = [s for s in self.list_sizes() if s.id == self.default['size']][0]
        image = [i for i in self.list_images() if i.id == self.default['image']][0]
        new_vm = super().create_node(name=name, image=image, size=size,
                                     ex_keyname=self.default['EC2_PRIVATE_KEY_FILE_NAME'],
                                     ex_securitygroup=self.default['EC2_SECURITY_GROUP'])

        return new_vm

    def set_public_ip(self, name, public_ip):
        print("No set_public_ip method")
        pass

    def remove_public_ip(self, name):
        print("No remove_public_ip method")
        pass
