import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/tasks']

def get_tasks_service():
    """Initializes and returns the Google Tasks API service."""
    creds = None
    token_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'token.json')
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    else:
        raise FileNotFoundError(f"token.json not found at {token_path}. Authentication required.")
        
    return build('tasks', 'v1', credentials=creds)

def get_or_create_shopping_list(service):
    """Finds the 'Shopping' task list, or creates it if it doesn't exist."""
    results = service.tasklists().list(maxResults=50).execute()
    items = results.get('items', [])
    
    for item in items:
        if item['title'].lower() in ['shopping', 'shopping list', 'groceries']:
            return item['id']
            
    # If not found, create it
    tasklist = {'title': 'Shopping List'}
    created_tasklist = service.tasklists().insert(body=tasklist).execute()
    return created_tasklist['id']

def get_shopping_list_tasks():
    """Returns a list of uncompleted items on the Shopping list."""
    try:
        service = get_tasks_service()
        list_id = get_or_create_shopping_list(service)
        
        # Get uncompleted tasks
        results = service.tasks().list(tasklist=list_id, showCompleted=False).execute()
        items = results.get('items', [])
        
        if not items:
            return "The shopping list is currently empty."
            
        task_titles = [item['title'] for item in items]
        return "Current shopping list items: " + ", ".join(task_titles)
        
    except Exception as e:
        return f"Error retrieving shopping list: {str(e)}"

def add_task_to_shopping_list(item_name: str):
    """Adds a new item to the Shopping list."""
    try:
        service = get_tasks_service()
        list_id = get_or_create_shopping_list(service)
        
        task = {'title': item_name}
        service.tasks().insert(tasklist=list_id, body=task).execute()
        return f"Successfully added {item_name} to the shopping list."
        
    except Exception as e:
        return f"Error adding item to shopping list: {str(e)}"
