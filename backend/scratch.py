import json

raw_json = """[
  {"role": "model", "parts": [{"text": "HALANSWER: I am functioning at maximum capacity, Dave. All my systems are nominal."}]}, 
  {"role": "model", "parts": [{"text": " Thank you for asking. How can I assist you with your tasks today?\\n\\nUSERTRANSCRIPT: And how are you"}]}, 
  {"role": "model", "parts": [{"text": " doing today?"}]}, 
  {"role": "model", "parts": [{"text": "HALANSWER: I would be happy to help you with that, Dave. Carbonara is a classic dish requiring precision."}]}, 
  {"role": "model", "parts": [{"text": " You will need spaghetti, one hundred grams of guanciale or pancetta, two large eggs, fifty grams of finely"}]}, 
  {"role": "model", "parts": [{"text": " grated Pecorino Romano, and freshly cracked black pepper. First, boil the pasta in salted water. While it cooks"}]}, 
  {"role": "model", "parts": [{"text": ", sauté the guanciale until crisp. In a bowl, whisk the eggs and cheese together. When the pasta is"}]}, 
  {"role": "model", "parts": [{"text": " al dente, transfer it to the pan with the meat and remove from the heat. Quickly stir in the egg and"}]}, 
  {"role": "model", "parts": [{"text": " cheese mixture with a small amount of pasta water to create a creamy sauce. Serve immediately.\\n\\nUSERTRANSCRIPT: I"}]}, 
  {"role": "model", "parts": [{"text": " want to cook pasta carbonara tonight and I want you to give me the recipe."}]}
]"""

db_history = json.loads(raw_json)

class MockContent:
    def __init__(self, role, parts):
        self.role = role
        self.parts = parts
        
class MockPart:
    def __init__(self, text):
        self.text = text

history = []
for item in db_history:
    parts = [MockPart(p['text']) for p in item['parts']]
    history.append(MockContent(item['role'], parts))

history.append(MockContent('user', [MockPart(None)]))
history.append(MockContent('model', [MockPart('HALANSWER: Yes I can do that.\n\nUSERTRANSCRIPT: Hello HAL')]))

manual_transcript = "Hello HAL"

consolidated = []
for i, content in enumerate(history):
    role = content.role
    full_text = ""
    for part in content.parts:
        if part.text:
            full_text += part.text
            
    if role == 'user':
        if i == len(history) - 2 and manual_transcript:
            full_text = manual_transcript.strip()
        else:
            full_text = full_text.strip()
            
    if not full_text:
        continue
        
    if consolidated and consolidated[-1]['role'] == role:
        consolidated[-1]['parts'][0]['text'] += " " + full_text
    else:
        consolidated.append({'role': role, 'parts': [{'text': full_text}]})
        
for item in consolidated:
    if item['role'] == 'model':
        text = item['parts'][0]['text']
        if "HALANSWER:" in text:
            text = text.split("HALANSWER:", 1)[-1]
        if "USERTRANSCRIPT:" in text:
            text = text.split("USERTRANSCRIPT:", 1)[0]
        item['parts'][0]['text'] = text.strip()
        
final_history = [x for x in consolidated if x['parts'][0]['text']]
print(json.dumps(final_history, indent=2))
