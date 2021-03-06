import os
import yaml
from pathlib import Path
from CloudFile import CloudFile
from db.DBProviderABC import DBProviderABC

class LocalDBProvider(DBProviderABC):
    """
    The local DB provider uses a folder with yaml files representing each cloud resource.
    """

    def __init__(self, db_path):
        '''
        Initialize local db provider by scanning for yaml files in in the path
        '''
        self._path = Path(db_path)

    def get(self, file_name):
        '''
        Get a CloudFile object corresponding to the given file name
        
        :param file_name: Corresponds to the CloudFile's `name`.
        :return: A CloudFile object
        '''
        files = self.list_files()
        
        if not files:
            return None

        return next(cf for cf in files if cf.name == file_name)

    def list_files(self):
        '''
        Return a list of Cloud Files tracked in this DB
        '''
        return [self._read_file(entry) for entry in list(self._path.glob('**/*.yaml'))]

    def add(self, cloud_file):
        '''
        Add a new Cloud File to the local DB

        :param cloud_file: A CloudFile instance.
        '''
        entry_path = self._get_entry_name(cloud_file)

        with open(entry_path, "w") as output:
            yaml.dump(cloud_file, output)

    def delete(self, cloud_file):
        '''
        Remove a CloudFile from the local db

        :param cloud_file: A could file entry
        :return:
        '''
        entry_path = self._get_entry_name(cloud_file)
        os.remove(entry_path)

    def update(self, cloud_file):
        '''
        Update an existing Cloud File entry
        '''
        self.add(cloud_file)

    def _get_entry_name(self, cloud_file):
        '''
        Gets the file name for the db entry

        :param cloud_file: A cloud file entry.  
        :return: A file location for the cloud entry on disk.
        '''
        file_name = cloud_file.name + ".yaml"
        return self._path.joinpath(file_name)

    def _read_file(self, yaml_file_path):
        '''
        Read a yaml file from disk and return the python object it represents.
        '''
        obj = {}
        with open(yaml_file_path, "r") as stream:
            try:
                obj = yaml.load(stream)
            except yaml.YAMLError as ex:
                print(ex)    
        return obj
        
