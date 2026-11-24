import unittest,os
from unittest.mock import patch,Mock
from app import app,CACHE
class Test(unittest.TestCase):
 def test_group_cache_filter(self):
  CACHE.clear(); row=dict(brand='Volkswagen',number='5G0880201Q',name='airbag unit for steering wheel',markt_name='USA',has_replacements=False)
  r=Mock(status_code=200);r.json.return_value={'success':True,'data':{'count':2,'results':[row,dict(row,markt_name='Brazil')]}}
  with patch.dict(os.environ,{'PLAN_PARTS_API_KEY':'test','AUTORA_ACCESS_TOKEN':'local'}),patch('app.requests.get',return_value=r) as get:
   c=app.test_client(); h={'X-Autora-Token':'local'}
   self.assertEqual(c.get('/oem?q=5G0880201Q').status_code,401)
   a=c.get('/oem?q=5G0880201Q',headers=h).json; self.assertEqual(len(a['items']),1);self.assertEqual(a['items'][0]['description'],'Vezetőoldali kormánylégzsák')
   self.assertEqual(c.get('/oem?q=5G0880201Q&market=USA',headers=h).json['cached'],True);self.assertEqual(get.call_count,1)
if __name__=='__main__': unittest.main()
