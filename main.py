import json
import time
import requests
import queue
import threading
import os
requests.packages.urllib3.disable_warnings()
import hashlib

cb_sensor_list = {}
q = queue.Queue()

with open("config.json") as fd:
    cfg = json.load(fd)

cb_api = cfg.get("cb_api")
cb_url = cfg.get("cb_url")
req_dirs = cfg.get("req_dirs")
acquisition_type = cfg.get("acquisition_type")
include_endpoints = cfg.get("include_endpoints")
exclude_endpoints = cfg.get("exclude_endpoints")
output_folder = cfg.get("output_folder")
workers = cfg.get("workers")
payload = {'X-Auth-Token': cb_api}

def cb_queue_all_things():
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    if cb_api == None or cb_url == None:
        print("> Your configuration file has missing or invalid parameters. Please check your configuration file.")
        exit()

    try:
        r = requests.get("{}/api/v1/sensor".format(cb_url), headers=payload, verify=False, timeout=180)
        snr_list = r.json()
        for s in snr_list:
            sensor_id = s.get('id')
            hostname = s.get("computer_name")
            cb_sensor_list[sensor_id] = hostname
            if len(include_endpoints) == 0:
                pass

            else:
                if sensor_id not in include_endpoints:
                    continue

            # Exclude any endpoints
            if sensor_id in exclude_endpoints:
                continue

            q.put(sensor_id)

        ## If no sensors in list, return
        if queue.Queue.qsize(q) == 0:
            return

        workers_list = []
        print("Items in queue: {}".format(queue.Queue.qsize(q)))

        ## CBLR limit is 10 LR sessions.
        for i in range(workers):
            stk = CB_ACQUIRE(cb_url, q, payload,)
            worker = threading.Thread(target=stk.begin, daemon=True)
            worker.start()
            workers_list.append(worker)
        q.join()

    except Exception as e:
        print(e)
        return

class CB_ACQUIRE():

        #### The Flow
        ## Get Session w/ check existing
        ## Send FL
        ## GET LISTING
        ## REQUEST file
        ## Download
        ## Cleanup
        ## Kill Session

    def __init__(self, cb_url, q, payload):
        self.q = q
        self.payload = payload
        self.cb_url = cb_url

    def begin(self):

        while queue.Queue.qsize(self.q) != 0:
            try:
                self.sensor_id = self.q.get(timeout=1)
                print("Items left in Queue: {}".format(queue.Queue.qsize(self.q)))
                self.cr = {"sensor_id": int(self.sensor_id)}
                print(self.sensor_id)

                fetch_session_id = self.open_session()

                if not fetch_session_id.get("session_id"):
                    self.q.put(self.sensor_id)
                    self.q.task_done()
                    continue

                session_id = fetch_session_id.get("session_id")
                print("Session ID is: {}".format(session_id))
                for d in req_dirs:

                    if acquisition_type == 0:
                        file_id = self.request_file(session_id, d)
                        if file_id == False:
                            continue
                        elif file_id == "bailed": ## means the session timed out, so we need to requeue and close the session. Try again later
                            self.close_session(session_id, self.sensor_id)
                            self.q.task_done()
                            break

                        if not self.download_file(session_id, file_id, d.split("\\")[-1:][0], d):
                            continue

                    elif acquisition_type == 1:
                        filelisting = self.send_fileListing(session_id, d)
                        if not filelisting:
                            ## Means it failed or path not found
                            self.q.task_done()
                            continue

                        obj_path = filelisting.get('object')
                        for filename in filelisting.get('files'):
                            if filename.get('filename') == '.' or filename.get('filename') == '..':
                                continue

                            fullPath = "{}{}".format(obj_path, filename.get('filename'))
                            print("{}{}".format(obj_path, filename.get('filename')))

                            file_id = self.request_file(session_id, fullPath)
                            if file_id == False:
                                continue
                            elif file_id == "bailed": ## means the session timed out, so we need to requeue and close the session. Try again later
                                self.close_session(session_id, self.sensor_id)
                                self.q.task_done()
                                break

                            time.sleep(4)
                            if not self.download_file(session_id, file_id, filename.get('filename'), fullPath):
                                # self.close_session(session_id, self.sensor_id)
                                # self.q.task_done()
                                continue

                if not self.close_session(session_id, self.sensor_id):
                    self.q.task_done()
                    continue

                self.q.task_done()
                continue

            except Exception as e:
                print(e)
                self.q.put(self.sensor_id)
                self.q.task_done()
                continue

    ### Methods for CBLR
    def open_session(self):
        try:
            r = requests.get("{}/api/v1/sensor/{}".format(cb_url, self.sensor_id), headers=payload, verify=False, timeout=180)
            snr_list = r.json()
            status = snr_list.get('status').lower()

            if status != "online":
                data_infoz = {}
                data_infoz["session_id"] = None
                data_infoz["error"] = "Sensor is offline. Trying again later"
                return data_infoz

            rq = requests.post('{}/api/v1/cblr/session'.format(self.cb_url), headers=self.payload, data=json.dumps(self.cr), verify=False,timeout=180)
            aq = rq.json()
            status = aq.get('status')
            session_id = aq.get('id')

            if status == "pending":
                while True:
                    req = requests.get('{}/api/v1/cblr/session/{}'.format(self.cb_url, session_id), headers=self.payload, data=json.dumps(self.cr), verify=False,timeout=180)
                    json_req = req.json()
                    status = json_req.get('status')
                    new_id = json_req.get('id')
                    cb_cwd = json_req.get('current_working_directory')
                    if status == "pending":
                        continue

                    elif status == "active":
                        data_infoz = {
                            "session_id": new_id,
                            "cb_cwd": cb_cwd
                        }
                        return data_infoz

                    elif status == "timeout" or status == "error":
                        data_infoz = [{
                            "session_id": None,
                            "error": json_req
                        }]
                        return data_infoz

                    else:
                        data_infoz = [{
                            "session_id": None,
                            "error": json_req
                        }]
                        return data_infoz
            else:
                data_infoz = {}
                data_infoz["session_id"] = None
                data_infoz["error"] = aq
                return data_infoz

        except Exception as e:
            print(e)
            session_open = {}
            session_open["session_id"] = None
            session_open["error"] = e
            return session_open

    def check_session_state(self, sensor_id):
        try:
            print("> Checking session for existing LR: {}".format(self.sensor_id))
            r = requests.get("{}/api/v1/cblr/session".format(self.cb_url), headers=self.payload, verify=False,timeout=180)
            sessions_stat = r.json()

            for s in sessions_stat:
                lr_status = s.get('status')
                snr_id = s.get('sensor_id')

                if snr_id == sensor_id:
                    if lr_status == "timeout":
                        return True

            return False

        except Exception as e:
            print(e)
            return False

    def send_fileListing(self, session_id, filepath):
        try:
            print("[X] Performing File Listing")
            push_push = requests.post('{}/api/v1/cblr/session/{}/command'.format(self.cb_url, session_id), headers=self.payload, data=json.dumps({"name": "directory list", "object": '{}'.format(filepath)}), verify=False,timeout=180)
            push_push_json = push_push.json()
            cmd_id = push_push_json.get('id')

            while True:
                do_check = requests.get('{}/api/v1/cblr/session/{}/command/{}'.format(self.cb_url, session_id, cmd_id), headers=self.payload, verify=False,timeout=180)
                out_go = do_check.json()
                call_status_push = out_go.get('status')

                if call_status_push == "pending":
                    continue

                elif call_status_push == "complete":
                    return out_go

                elif call_status_push == "error" or call_status_push == "timeout":
                    return False

                else:
                    return False

        except Exception as e:
            print(e)
            return False

    def request_file(self, session_id, filepath):
        try:
            print("> Requesting {} be sent to CBR server from sensor: {}".format(filepath, self.sensor_id))
            lk_up = requests.post('{}/api/v1/cblr/session/{}/command'.format(self.cb_url, session_id), headers=self.payload, data=json.dumps({"name": "get file", "object": filepath}), verify=False, timeout=180)
            lk_data = lk_up.json()
            cmd_id = lk_data.get('id')
            sensor_id = lk_data.get('sensor_id')

            while True:
                time.sleep(2)
                ss = self.check_session_state(sensor_id)
                if ss == False: ## Means the session hasn't timed out yet
                    do_check_job = requests.get('{}/api/v1/cblr/session/{}/command/{}'.format(self.cb_url, session_id, cmd_id), headers=self.payload, verify=False,timeout=180)
                    out_go_job = do_check_job.json()
                    master_status = out_go_job.get('status')
                    if master_status == "pending":
                        continue

                    elif master_status == "complete":
                        file_id = lk_data.get('file_id')
                        print("> Requested file {} is completed: File Id: {}".format(filepath, file_id))
                        return int(file_id)

                    elif master_status == "failed" or master_status == "error" or master_status == "timeout":
                        return False

                    else:
                        return False

                elif ss == True:
                    print("Session died, re-queuing sensor: {}".format(sensor_id))
                    q.put(session_id)
                    return "bailed"

        except Exception as e:
            print(e)
            return False

    def download_file(self, session_id, file_id, filename, original_full_path):
        try:
            print("> Downloading job output to files directory")
            r = requests.get('{}/api/v1/cblr/session/{}/file/{}/content'.format(self.cb_url, session_id, file_id), headers=self.payload, verify=False,timeout=180, stream=True)

            CBfileName = "{}_{}_{}_{}".format(self.sensor_id, cb_sensor_list.get(self.sensor_id), time.time(), original_full_path.replace("\\","_").replace("/","_"))
            with open("{}/{}".format(output_folder, CBfileName), 'wb+') as yyrf:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:
                        yyrf.write(chunk)
            try:
                with open("artifacts.txt", "a+") as al:
                    artifact = '\nFileItem | &nbsp;\n------ | -----\nFile Path | {}\nFile Name | {}\nFile Size (Bytes) | {}\nMD5 | {}\nSHA1 | {}\n'.format(
                            original_full_path.replace('\\', '\\\\'),
                            filename,
                            os.stat('{}/{}'.format(output_folder, CBfileName)).st_size,
                            hashlib.md5(open('{}/{}'.format(output_folder,CBfileName), 'rb').read()).hexdigest(),
                            hashlib.sha1(open('{}/{}'.format(output_folder,CBfileName), 'rb').read()).hexdigest())
                    al.write(artifact)

            except Exception as e:
                with open("artifacts-failed.txt", "a+") as alf:
                    alf.write("{}, {}\n".format(original_full_path, str(e)))
            return True

        except Exception as e:
            print(e)
            return "ERROR"

    def close_session(self, session_id, sensor_id):
        try:
            print("> Closing session: {}".format(session_id))
            r = requests.put('{}/api/v1/cblr/session/{}'.format(self.cb_url, session_id), headers=self.payload, data=json.dumps({"id": session_id, "sensor_id": sensor_id, "status": "close"}), verify=False,timeout=180)
            ## Just send and roll out
            return True

        except Exception as e:
            print(e)
            return False

if __name__ == '__main__':
    cb_queue_all_things()


