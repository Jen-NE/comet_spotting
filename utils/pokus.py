import requests
import urllib.parse

def get_comet_info(comet_id):
    """
    Fetches information for a specific comet from the NASA JPL Horizons API.
    """
    # 1. Wrap the ID in single quotes, which Horizons requires for names with spaces
    command_str = f"'{comet_id}'"
    
    # 2. Manually encode the command. This ensures quotes become %27 and spaces become %20
    encoded_command = urllib.parse.quote(command_str)
    
    # 3. Build the full URL manually instead of passing a dictionary to 'requests'.
    # This prevents the requests library from double-encoding or changing %20 to +
    url = (
        f"https://ssd.jpl.nasa.gov/api/horizons.api"
        f"?format=json"
        f"&COMMAND={encoded_command}"
        f"&OBJ_DATA=YES"
        f"&MAKE_EPHEM=NO" #request ephemeris data as well
        f"&EPHEM_TYPE=VECTORS"
    )
    
    print(f"Sending request to Exact URL: {url}\n")
    
    try:
        # Pass the pre-built URL string directly
        response = requests.get(url)
        response.raise_for_status() 
        
        data = response.json()
        
        if 'result' in data:
            return data['result']
        else:
            return "Error: Unexpected response format from JPL Horizons."
            
    except requests.exceptions.RequestException as e:
        return f"An error occurred while connecting to the API: {e}"

# --- Example Usage ---
if __name__ == "__main__":
    test_comet_id = "DSS2"
    
    comet_data = get_comet_info(test_comet_id)
    
    print("--- JPL Horizons Response ---")
    print(comet_data)