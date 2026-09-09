const { chromium } = require('/tmp/push2-browser-check/node_modules/playwright');
const path = require('path');
(async () => {
  const browser = await chromium.launch({channel:'chrome',headless:true,args:['--no-first-run']});
  const errors=[];
  for(const [name,width,height] of [['desktop',1280,1050],['mobile',390,844]]){
    const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
    page.on('pageerror',e=>errors.push(String(e)));
    page.on('console',m=>{if(m.type()==='error')console.log('browser',m.text());});
    await page.goto('file://'+path.resolve('push2_live_overlay_v2.html'));
    await page.waitForTimeout(2000);
    console.log('initial',await page.locator('#error').textContent(),errors);
    await page.screenshot({path:'/tmp/push2-overlay-initial.png'});
    await page.waitForFunction(()=>document.querySelectorAll('#pads .pad').length===64,{},{timeout:5000});
    await page.waitForFunction(()=>document.getElementById('lcd').naturalWidth===960);
    await page.screenshot({path:'/tmp/push2-overlay-'+name+'.png',fullPage:true});
    const metrics=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
      pads:document.querySelectorAll('#pads .pad').length,targets:document.querySelectorAll('.targetrow').length,
      lcdWidth:document.getElementById('lcd').naturalWidth,error:document.getElementById('error').textContent}));
    console.log(name,metrics);
    if(metrics.scrollWidth>metrics.width)throw new Error(name+' horizontal overflow');
    await page.locator('#pads .pad').first().click();
    if(!await page.locator('#detail').isVisible())throw new Error('Inspector did not open');
    await page.locator('#close').click();
    await page.close();
  }
  await browser.close();
  if(errors.length)throw new Error(errors.join('\n'));
})().catch(e=>{console.error(e);process.exit(1);});
