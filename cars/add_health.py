with open('views.py', 'a') as f:
    f.write('\n\n')
    f.write("# Health Check\n")
    f.write("from django.http import JsonResponse\n")
    f.write("def health_check(request):\n")
    f.write("    return JsonResponse({'status': 'ok'})\n")
print('done')
