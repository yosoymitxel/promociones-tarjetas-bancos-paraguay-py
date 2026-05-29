import json
with open('output/promos.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Total promos: {len(data)}")

# Check for null desc, empty href, and empty img
issues = []
for i, p in enumerate(data):
    desc = p.get('desc')
    href = p.get('href', '')
    img = p.get('img', '')
    # Consider img empty if it's empty string or maybe a dict? but we converted to string
    if desc is None and (not href or href.strip() == '') and (not img or img.strip() == ''):
        issues.append((i, p.get('title', 'NO TITLE'), p.get('bankId')))

print(f"Found {len(issues)} promos with null desc, empty href, and empty img")
if issues:
    print("First 5:")
    for i, title, bank in issues[:5]:
        print(f"  {title} ({bank})")

# Also check for continental specifically
continental_issues = [issue for issue in issues if issue[2] == 'continental']
print(f"\nContinental issues: {len(continental_issues)}")
if continental_issues:
    print("First 5 continental issues:")
    for i, title, bank in continental_issues[:5]:
        print(f"  {title} ({bank})")

# Check for entries with category matching title (after removing emoji and lowercasing)
import re
def strip_emoji(s):
    return re.sub(r'[^\w\s]', '', s).strip().lower()

category_title_matches = []
for p in data:
    title = p.get('title', '')
    category = p.get('category', '')
    if title and category:
        if strip_emoji(title) == strip_emoji(category):
            category_title_matches.append(p)

print(f"\nEntries where category matches title (ignoring emojis): {len(category_title_matches)}")
if category_title_matches:
    print("First 5:")
    for p in category_title_matches[:5]:
        print(f"  Title: {p.get('title')}, Category: {p.get('category')}, Bank: {p.get('bankId')}")
