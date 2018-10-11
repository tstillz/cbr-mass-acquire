# Carbon Black Response: Mass Acquire
This script enables responders and analysts using Carbon Black Response to perform mass file acquisitions. 

This script is related to the blog post: https://blog.stillztech.com/2018/10/carbon-black-response-mass-acquire.html 

## Usage

Update the `config.json` with your Carbon Black URL and API token. 

Update the `acquisition_type` value with the type of acquisition you want to perform:
- 0: single file w/ dir -> `["C:\\evil.exe"]`
- 1: Lists all items in a given directory and attempts to acquire each file inside that directory -> `["C:\\inetpub\\Logs\\LogFiles\\W3SVC1\\"]`

Update the `endpoints` array with a list of the sensors ID's you wish to acquire the files from. `If the list is empty, the script assumes ALL endpoints.` 

Update the `req_dirs` with a list of either full file paths or directories depends on what you've set `acquisition_type` too. 
 
After these values above have been updated, you will need to install the request library:
> pip3 install requests

Run the script:
> python3 main.py

The each file this is acquired will be saved into your output directory, specified by `output_folder`. 
In addition, i've also added in a `artifacts.txt` file to format each acquired file into markdown format to help with reporting/tracking of acquired files. 

## Extras
Inside the `config.json`, you'll see a key called `req_dir_extras`. 
These are extra items i've used in many engagements that may be useful for you. 
Just copy the items in the array into the `req_dirs` and set the appropriate `acquistion_type`.  

