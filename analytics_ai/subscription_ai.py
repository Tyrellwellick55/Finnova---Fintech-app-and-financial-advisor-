def analyze_subscriptions(subs, income):

    total = float(sum(s.amount for s in subs))
    ratio = total / max(float(income), 1.0)

    if ratio > 0.6:
        return {
            'risk': 'HIGH',
            'action': 'PAUSE_NON_ESSENTIAL'
        }

    return {
        'risk': 'LOW',
        'action': 'SAFE'
    }
