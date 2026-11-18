with open('alerts.py') as f:
    content = f.read()

if 'send_sms' not in content:
    content = content.replace('from .emails import send_price_drop_alert, send_back_in_stock_alert\n\n\n',
        'from .emails import send_price_drop_alert, send_back_in_stock_alert\nfrom .sms import send_sms\n\n\n')
    
    helper = 'def _get_user_phone(user):\n    profile = getattr(user, "profile", None)\n    if profile and hasattr(profile, "phone") and profile.phone:\n        return profile.phone\n    customer = getattr(user, "customer", None)\n    if customer and hasattr(customer, "phone") and customer.phone:\n        return customer.phone\n    return None\n\n\n'
    content = content.replace('def _get_favorited_users_for_car(car):\n    """Return users who favorited a car with their profile/preferences."""\n    favorites = (\n        car.favorited_by.select_related(\'user\', \'user__profile\')\n        .all()\n    )\n    return favorites\n\n\n',
        'def _get_favorited_users_for_car(car):\n    """Return users who favorited a car with their profile/preferences."""\n    favorites = (\n        car.favorited_by.select_related(\'user\', \'user__profile\')\n        .all()\n    )\n    return favorites\n\n\n' + helper)
    
    old = '            try:\n                send_price_drop_alert(user, car, fav.price_at_save, history.new_price)\n                PriceDropAlert.objects.create(user=user, car=car, price_history=history)\n                price_drops_sent += 1\n            except Exception:\n                logger.exception(\'Failed to send price-drop alert for car %s to %s\', car.pk, user.email)'
    new = '            try:\n                send_price_drop_alert(user, car, fav.price_at_save, history.new_price)\n                phone = _get_user_phone(user)\n                if phone:\n                    try:\n                        msg = f"Price drop! {car.year} {car.make} {car.model} now {history.new_price}."\n                        send_sms(phone, msg)\n                    except Exception:\n                        logger.exception(\'Failed to send SMS price-drop alert for car %s to %s\', car.pk, phone)\n                PriceDropAlert.objects.create(user=user, car=car, price_history=history)\n                price_drops_sent += 1\n            except Exception:\n                logger.exception(\'Failed to send price-drop alert for car %s to %s\', car.pk, user.email)'
    if old in content:
        content = content.replace(old, new)
    
    old2 = '            try:\n                send_back_in_stock_alert(user, car)\n                BackInStockAlert.objects.create(user=user, car=car, status_history=history)\n                back_in_stock_sent += 1\n            except Exception:\n                logger.exception(\'Failed to send back-in-stock alert for car %s to %s\', car.pk, user.email)'
    new2 = '            try:\n                send_back_in_stock_alert(user, car)\n                phone = _get_user_phone(user)\n                if phone:\n                    try:\n                        msg = f"Back in stock! {car.year} {car.make} {car.model} is available again."\n                        send_sms(phone, msg)\n                    except Exception:\n                        logger.exception(\'Failed to send SMS back-in-stock alert for car %s to %s\', car.pk, phone)\n                BackInStockAlert.objects.create(user=user, car=car, status_history=history)\n                back_in_stock_sent += 1\n            except Exception:\n                logger.exception(\'Failed to send back-in-stock alert for car %s to %s\', car.pk, user.email)'
    if old2 in content:
        content = content.replace(old2, new2)
    
    with open('alerts.py', 'w') as f:
        f.write(content)
    print('done')
else:
    print('exists')
