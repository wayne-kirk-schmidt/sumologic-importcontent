#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=C0206

"""
Exaplanation: Sumo Logic Import content files and folders into Sumo Logic

Usage:
   $ python  sumologic_importcontent  [ options ]

Style:
   Google Python Style Guide:
   http://google.github.io/styleguide/pyguide.html

    @name           sumologic_importcontent
    @version        2.00
    @author-name    Wayne Schmidt
    @author-email   wschmidt@sumologic.com
    @license-name   Apache 2.0
    @license-url    https://www.apache.org/licenses/LICENSE-2.0
"""

__version__ = 2.00
__author__ = "Wayne Schmidt (wschmidt@sumologic.com)"

### beginning ###
import json
import os
import sys
import time
import datetime
import argparse
import configparser
import http
import requests

sys.dont_write_bytecode = 1

MY_CFG = 'undefined'
PARSER = argparse.ArgumentParser(description="""

Allows you to import content from a directory tree of files

""")

PARSER.add_argument("-a", metavar='<secret>', dest='MY_SECRET', \
                    help="set api (format: <key>:<secret>) ")

PARSER.add_argument("-k", metavar='<client>', dest='MY_CLIENT', \
                    help="set key (format: <site>_<orgid>) ")

PARSER.add_argument("-c", metavar='<configfile>', dest='CONFIG', \
                    help="Specify config file")

PARSER.add_argument("-s", metavar='<sources>', dest='IMPORTSRC', \
                    required = True, help="Specify items to import")

PARSER.add_argument("-d", metavar='<importdst>', dest='IMPORTDST', \
                    required = True, help="Specify import destination")

PARSER.add_argument("-v", type=int, default=0, metavar='<verbose>', \
                    dest='verbose', help="increase verbosity")

ARGS = PARSER.parse_args()

DELAY_TIME = .5

IMPORTSRC = {}
IMPORTSRC['file'] = {}
IMPORTSRC['folder'] = {}

IMPORTDST = {}
IMPORTDST['file'] = {}
IMPORTDST['folder'] = {}

REPORTTAG = 'sumologic-import'

REPORTLOGDIR = '/var/tmp'

RIGHTNOW = datetime.datetime.now()

DATESTAMP = RIGHTNOW.strftime('%Y%m%d')

TIMESTAMP = RIGHTNOW.strftime('%H%M%S')

def resolve_option_variables():
    """
    Validates and confirms all necessary variables for the script
    """

    if ARGS.MY_SECRET:
        (keyname, keysecret) = ARGS.MY_SECRET.split(':')
        os.environ['SUMO_UID'] = keyname
        os.environ['SUMO_KEY'] = keysecret

    if ARGS.MY_CLIENT:
        (deployment, organizationid) = ARGS.MY_CLIENT.split('_')
        os.environ['SUMO_LOC'] = deployment
        os.environ['SUMO_ORG'] = organizationid

def resolve_config_variables():
    """
    Validates and confirms all necessary variables for the script
    """

    if ARGS.CONFIG:
        cfgfile = os.path.abspath(ARGS.CONFIG)
        configobj = configparser.ConfigParser()
        configobj.optionxform = str
        configobj.read(cfgfile)

        if ARGS.verbose > 8:
            print('Displaying Config Contents:')
            print(dict(configobj.items('Default')))

        if configobj.has_option("Default", "SUMO_TAG"):
            os.environ['SUMO_TAG'] = configobj.get("Default", "SUMO_TAG")

        if configobj.has_option("Default", "SUMO_UID"):
            os.environ['SUMO_UID'] = configobj.get("Default", "SUMO_UID")

        if configobj.has_option("Default", "SUMO_KEY"):
            os.environ['SUMO_KEY'] = configobj.get("Default", "SUMO_KEY")

        if configobj.has_option("Default", "SUMO_LOC"):
            os.environ['SUMO_LOC'] = configobj.get("Default", "SUMO_LOC")

        if configobj.has_option("Default", "SUMO_END"):
            os.environ['SUMO_END'] = configobj.get("Default", "SUMO_END")

        if configobj.has_option("Default", "SUMO_ORG"):
            os.environ['SUMO_ORG'] = configobj.get("Default", "SUMO_ORG")

def initialize_variables():
    """
    Validates and confirms all necessary variables for the script
    """

    resolve_option_variables()

    resolve_config_variables()

    try:
        my_uid = os.environ['SUMO_UID']
        my_key = os.environ['SUMO_KEY']

    except KeyError as myerror:
        print(f'Environment Variable Not Set :: {myerror.args[0]}')

    return my_uid, my_key

( sumo_uid, sumo_key ) = initialize_variables()

def resolve_import_sources():
    """
    Resolve all of the entries into a list of items.
    Directories are created relative to importdst as folders.
    Files are loaded as content.
    """

    if os.path.isdir(ARGS.IMPORTSRC):
        for myroot, _mysubdirs, myfiles in os.walk(ARGS.IMPORTSRC):
            for myfilename in myfiles:
                myfilepath = os.path.join(myroot, myfilename)
                with open(myfilepath, encoding='utf8') as myfileobject:
                    mycontents = json.load(myfileobject)
                    if 'itemType' not in mycontents:
                        mycontenttype = mycontents['type']
                        if mycontenttype != 'Folder':
                            IMPORTSRC['file'][os.path.abspath(myfilepath)] = 'pending'
    else:
        with open(ARGS.IMPORTSRC, encoding='utf8') as myfileobject:
            mycontents = json.load(myfileobject)
            if 'itemType' not in mycontents:
                mycontenttype = mycontents['type']
                if mycontenttype != 'Folder':
                    IMPORTSRC['file'][os.path.abspath(myfilepath)] = 'pending'

def create_import_point(source):
    """
    Create a folder for all of the content imported
    """

    create_import_dir = 'yes'

    results = source.get_myfolders()

    for child in results['children']:
        if child['name'] == ARGS.IMPORTDST:
            create_import_dir = 'no'
            folder_id = child['id']
            folder_name = child['name']

    if create_import_dir == 'yes':
        personal_folder_id = source.get_myfolders()['id']
        results = source.make_folder(ARGS.IMPORTDST, personal_folder_id)
        folder_id = results['id']
        folder_name = results['name']
        folder_tag = "CREATED"
    else:
        folder_tag = "EXISTING"

    if ARGS.verbose > 5:
        print(f'{folder_tag}:: {folder_id} - {folder_name}')

    IMPORTDST['folder'][folder_name] = folder_id

    return folder_id

def import_content(source, parentid):
    """
    Load the identified content into Sumo Logic
    """

    for sourcefile in IMPORTSRC['file']:
        with open(sourcefile, "r", encoding='utf8') as sourceobject:
            if ARGS.verbose > 5:
                print(f'UPLOAD: {sourcefile}')
            jsonpayload = json.load(sourceobject)
            result = source.start_import_job(parentid, jsonpayload)
            jobid = result['id']
            status = source.check_import_job_status(parentid, jobid)
            if ARGS.verbose > 9:
                print(f'STATUS: {status}')
            while status['status'] == 'InProgress':
                status = source.check_import_job_status(parentid, jobid)
                if ARGS.verbose > 9:
                    print(f'STATUS: {status}')
                time.sleep(DELAY_TIME)
            IMPORTDST['file'][sourcefile] = status['status']
            if status['status'] == 'Failed':
                print('----------------------------')
                print(f'FILE: {sourcefile}')
                print(f'STATUS: {status}')
                print('----------------------------')

def print_import_maps():
    """
    Prints out current state of the IMPORTSRC and IMPORTDST maps
    """

    if ARGS.verbose > 8:
        for content_type in IMPORTSRC:
            for keys,values in IMPORTSRC[content_type].items():
                print(f'{content_type}: {values} - {keys}')

    if ARGS.verbose > 5:
        for content_type in IMPORTDST:
            for keys,values in IMPORTDST[content_type].items():
                print(f'{content_type}: {values} - {keys}')

def create_import_manifest_file(restoredir, restoreoid):
    """
    Now display the output we want from the RESTORERECORD data structure we made.
    """
    manifestname = f'{REPORTTAG}.{DATESTAMP}.{TIMESTAMP}.csv'
    manifestfile = os.path.join(REPORTLOGDIR, manifestname)

    if ARGS.verbose > 6:
        print(f'Creating Restore-Manifest: {manifestfile}')

    with open(manifestfile, 'a', encoding='utf8') as manifestobject:
        manifestobject.write(f'{"type"},{"parent_name"},{"parent_oid"}, \
                             {"dst_oid"}, {"src_file"}\n')
        for content_item in IMPORTDST['file']:
            dst_file = content_item
            dst_oid = IMPORTDST['file'][content_item]
            manifestobject.write(f'{"file"},{restoredir},{restoreoid},{dst_oid},{dst_file}\n')

def main():
    """
    Setup the Sumo API connection, using the required tuple of region, id, and key.
    Once done, then run through the commands required
    """

    if ARGS.verbose > 3:
        print("Step-01: - Authenticating")

    source = SumoApiClient(sumo_uid, sumo_key)

    if ARGS.verbose > 3:
        print("Step-02: - Creating Import Folder")

    importid = create_import_point(source)

    if ARGS.verbose > 3:
        print("Step-03: - Resolving sources")

    resolve_import_sources()

    print_import_maps()

    if ARGS.verbose > 3:
        print("Step-04: - Importing Content to Folders")

    import_content(source,importid)

    print_import_maps()

    if ARGS.verbose > 3:
        print("Step-05: - Write Out Imported Content Manifest")

    create_import_manifest_file(ARGS.IMPORTDST, importid)

### class ###

class SumoApiClient():
    """
    This is defined SumoLogic API Client
    The class includes the HTTP methods, cmdlets, and init methods
    """

    def __init__(self, access_id, access_key, endpoint=None, cookie_file='cookies.txt'):
        """
        Initializes the Sumo Logic object
        """
        self.session = requests.Session()
        self.session.auth = (access_id, access_key)
        self.session.headers = {'content-type': 'application/json', \
            'accept': 'application/json'}
        cookiejar = http.cookiejar.FileCookieJar(cookie_file)
        self.session.cookies = cookiejar
        if endpoint is None:
            self.endpoint = self._get_endpoint()
        elif len(endpoint) < 3:
            self.endpoint = 'https://api.' + endpoint + '.sumologic.com/api'
        else:
            self.endpoint = endpoint
        if self.endpoint[-1:] == "/":
            raise Exception("Endpoint should not end with a slash character")

    def _get_endpoint(self):
        """
        SumoLogic REST API endpoint changes based on the geo location of the client.
        It contacts the default REST endpoint and resolves the 401 to get the right endpoint.
        """
        self.endpoint = 'https://api.sumologic.com/api'
        self.response = self.session.get('https://api.sumologic.com/api/v1/collectors')
        endpoint = self.response.url.replace('/v1/collectors', '')
        return endpoint

    def delete(self, method, params=None, headers=None, data=None):
        """
        Defines a Sumo Logic Delete operation
        """
        response = self.session.delete(self.endpoint + method, \
            params=params, headers=headers, data=data)
        if response.status_code != 200:
            response.reason = response.text
        response.raise_for_status()
        return response

    def get(self, method, params=None, headers=None):
        """
        Defines a Sumo Logic Get operation
        """
        response = self.session.get(self.endpoint + method, \
            params=params, headers=headers)
        if response.status_code != 200:
            response.reason = response.text
        response.raise_for_status()
        return response

    def post(self, method, data, headers=None, params=None):
        """
        Defines a Sumo Logic Post operation
        """
        response = self.session.post(self.endpoint + method, \
            data=json.dumps(data), headers=headers, params=params)
        if response.status_code != 200:
            response.reason = response.text
        response.raise_for_status()
        return response

    def put(self, method, data, headers=None, params=None):
        """
        Defines a Sumo Logic Put operation
        """
        response = self.session.put(self.endpoint + method, \
            data=json.dumps(data), headers=headers, params=params)
        if response.status_code != 200:
            response.reason = response.text
        response.raise_for_status()
        return response

### class ###

### methods ###

    def get_myfolders(self):
        """
        This uses a GET to retrieve all information.
        """
        url = "/v2/content/folders/personal/"
        body = self.get(url).text
        results = json.loads(body)
        return results

    def get_myfolder(self, myself):
        """
        This uses a GET to retrieve single item information.
        """
        url = "/v2/content/folders/" + str(myself)
        body = self.get(url).text
        results = json.loads(body)
        time.sleep(DELAY_TIME)
        return results

    def make_folder(self, myname, myparent):
        """
        Create a folder
        """

        folderpayload = {}
        folderpayload['name'] = str(myname)
        folderpayload['description'] = str(myname)
        folderpayload['parentId'] = str(myparent)

        url = "/v2/content/folders"
        body = self.post(url,data=folderpayload).text
        results = json.loads(body)
        time.sleep(DELAY_TIME)
        return results

    def get_globalfolders(self):
        """
        This uses a GET to retrieve all connection information.
        """
        url = "/v2/content/folders/global"
        body = self.get(url).text
        results = json.loads(body)
        return results

    def get_globalfolder(self, myself):
        """
        This uses a GET to retrieve single connection information.
        """
        url = "/v2/content/folders/global/" + str(myself)
        body = self.get(url).text
        results = json.loads(body)
        return results

    def start_export_job(self, myself):
        """
        This starts an export job by passing in the content ID
        """
        url = "/v2/content/" + str(myself) + "/export"
        body = self.post(url, data=str(myself)).text
        results = json.loads(body)
        return results

    def check_export_job_status(self, myself,jobid):
        """
        This starts an export job by passing in the content ID
        """
        url = "/v2/content/" + str(myself) + "/export/" + str(jobid) + "/status"
        time.sleep(DELAY_TIME)
        body = self.get(url).text
        results = json.loads(body)
        return results

    def check_export_job_result(self, myself,jobid):
        """
        This starts an export job by passing in the content ID
        """
        url = "/v2/content/" + str(myself) + "/export/" + str(jobid) + "/result"
        time.sleep(DELAY_TIME)
        body = self.get(url).text
        results = json.loads(body)
        return results

    def start_import_job(self, folderid, content, adminmode=False, overwrite=False):
        """
        This starts an import job by passing in the content ID and content
        """
        headers = {'isAdminMode': str(adminmode).lower()}
        params = {'overwrite': str(overwrite).lower()}
        url = "/v2/content/folders/" + str(folderid) + "/import"
        time.sleep(DELAY_TIME)
        body = self.post(url, content, headers=headers, params=params).text
        results = json.loads(body)
        return results

    def check_import_job_status(self, folderid, jobid, adminmode=False):
        """
        This checks on the status of an import content job
        """
        headers = {'isAdminMode': str(adminmode).lower()}
        url = "/v2/content/folders/" + str(folderid) + "/import/" + str(jobid) + "/status"
        time.sleep(DELAY_TIME)
        body = self.get(url, headers=headers).text
        results = json.loads(body)
        return results

### methods ###

if __name__ == '__main__':
    main()
