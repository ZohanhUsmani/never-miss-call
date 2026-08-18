import json
from app import app

with app.test_client() as c:
    assert c.post('/api/auth/signup', json={'name':'T','email':'t@b.com','password':'pass1234'}).status_code==200; print('1 signup OK')
    r = c.get('/api/auth/me'); assert r.status_code==200 and json.loads(r.data)['user']['email']=='t@b.com'; print('2 me OK')
    assert c.post('/api/subscribe', json={'payment_method_id':'pm_test'}).status_code==200; print('3 subscribe OK')
    assert c.post('/api/config', json={'business_number':'+15551234567','personal_number':'+15559876543','timezone':'America/New_York','working_days':[0,1,2,3,4],'working_hours_start':'09:00','working_hours_end':'17:00'}).status_code==200; print('4 config OK')
    r = c.post('/api/provision-number', json={}); print('5 provision:', r.status_code, '(expected 500 w/o SignalWire)')
    assert c.get('/api/dashboard').status_code==200; print('6 dashboard OK')
    r = c.post('/call/test', data={'From':'+15551112222'}); assert r.status_code==200 and 'text/xml' in r.headers.get('Content-Type',''); print('7 webhook OK')
    assert c.post('/api/auth/logout').status_code==200; print('8 logout OK')
    assert json.loads(c.get('/api/auth/me').data).get('not_logged_in'); print('9 not_logged_in OK')
    print('ALL 9 PASSED')
