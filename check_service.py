with open('cars/views.py') as f:
    content = f.read()
idx = content.find('# Service bookings')
if idx >= 0:
    end = content.find('# Live Chat Integration', idx)
    if end == -1:
        end = idx + 800
    print(content[idx:end])
