(function () {
  const { ref, reactive, computed, onMounted, onUnmounted } = Vue;
  window.CS2VideoWizard = {
    props: { token: String },
    setup(props) {
      const boot = reactive({ players:[], presets:[], packaging_presets:[], bgm_presets:[], wechat_targets:[], health:{} });
      const step = ref(1), player = ref(null), matches = ref([]), selectedMatch = ref(null), job = ref(null), jobs = ref([]);
      const query = ref(null), loading = ref(false), error = ref(''), selected = ref([]), settingsOpen = ref(false);
      const settings = reactive({ai_mode:false,cs2_path:'',ffmpeg_path:'',montage_encoder:'auto',obs_transition_enabled:false,obs_transition_name:'Fade',obs_transition_duration_ms:100,kb_overlay_enabled:false,kb_overlay_tick_offset:6,kb_overlay_position:'bottom_center',kill_fx_enabled:false,kill_fx_tick_offset:6,recording_global_pacing:{},default_record_warmup:{}});
      const output = reactive({ preset_id:'highlight-16x9', packaging_id:'clean', bgm_id:'none', wechat_target:'' });
      let timer = null;
      async function api(path, options={}) {
        const response = await fetch(path, { ...options, headers:{'Content-Type':'application/json','Authorization':'Bearer '+props.token} });
        const body = await response.json(); if (!response.ok) throw new Error(body.detail || '请求失败'); return body.data;
      }
      function targetValue(t){ return typeof t === 'string' ? t : t.id; }
      function targetLabel(t){ return typeof t === 'string' ? t : (t.label || t.id); }
      function stat(value, digits=0){ return typeof value==='number' ? value.toFixed(digits) : '--'; }
      function signed(value){ return typeof value==='number' ? (value>0?'+':'')+value : ''; }
      async function load() {
        try { Object.assign(boot, await api('/api/cs2-video/bootstrap')); Object.assign(settings, await api('/api/cs2-video/settings')); jobs.value=(await api('/api/cs2-video/jobs')).jobs||[];
          if (!output.wechat_target && boot.wechat_targets.length) output.wechat_target=targetValue(boot.wechat_targets[0]);
        } catch(e){ error.value=e.message; }
      }
      async function choosePlayer(p) { player.value=p; selectedMatch.value=null; matches.value=[]; loading.value=true; error.value='';
        try { query.value=await api('/api/cs2-video/match-queries',{method:'POST',body:JSON.stringify({player_id:p.steamid})}); step.value=2; }
        catch(e){error.value=e.message} finally{loading.value=false}
      }
      async function poll() {
        try {
          if (query.value && !['completed','failed'].includes(query.value.status)) { query.value=await api('/api/cs2-video/match-queries/'+query.value.id); matches.value=query.value.matches||[]; if(query.value.status==='failed')error.value=query.value.error; }
          const data=await api('/api/cs2-video/jobs'); jobs.value=data.jobs||[];
          if(job.value){ const fresh=jobs.value.find(x=>x.id===job.value.id); if(fresh){job.value=fresh; if(fresh.status==='awaiting_clip_selection')step.value=3;} }
        } catch(e) { /* next poll retries */ }
      }
      async function createJob() { if(!selectedMatch.value)return; loading.value=true; error.value=''; try { job.value=await api('/api/cs2-video/jobs',{method:'POST',body:JSON.stringify({query_id:query.value.id,match_id:selectedMatch.value.match_id})}); step.value=3; await poll(); } catch(e){error.value=e.message} finally{loading.value=false} }
      function toggle(key){ selected.value=selected.value.includes(key)?selected.value.filter(x=>x!==key):[...selected.value,key]; }
      async function submit(){ loading.value=true; error.value=''; try{ job.value=await api('/api/cs2-video/jobs/'+job.value.id+'/render',{method:'POST',body:JSON.stringify({...output,event_keys:selected.value})}); step.value=4; await poll(); }catch(e){error.value=e.message}finally{loading.value=false} }
      async function action(id,name){ try{await api('/api/cs2-video/jobs/'+id+'/'+name,{method:'POST'});await poll()}catch(e){error.value=e.message} }
      async function saveSettings(){loading.value=true;error.value='';try{await api('/api/cs2-video/settings',{method:'PUT',body:JSON.stringify({settings})});settingsOpen.value=false}catch(e){error.value=e.message}finally{loading.value=false}}
      onMounted(()=>{load();timer=setInterval(poll,3000)}); onUnmounted(()=>clearInterval(timer));
      return {boot,step,player,matches,selectedMatch,job,jobs,query,loading,error,selected,output,settings,settingsOpen,choosePlayer,createJob,toggle,submit,action,saveSettings,targetValue,targetLabel,stat,signed};
    },
    template:`<section class="cs2v">
      <div class="cs2v-head"><div><h2>CS2 视频制作</h2><div class="cs2v-muted">选择比赛高光，生成视频并发送到微信</div></div><div class="cs2v-health"><span :class="boot.health.downloader===true?'ok':boot.health.downloader===false?'bad':''">下载器</span><span :class="boot.health.insight===true?'ok':boot.health.insight===false?'bad':''">Insight</span><span :class="boot.health.bot===true?'ok':boot.health.bot===false?'bad':''">微信 Bot</span><button class="btn-sm" @click="settingsOpen=!settingsOpen">设置</button></div></div>
      <div v-if="settingsOpen" class="cs2v-panel cs2v-settings"><h3>视频制作设置</h3><div class="cs2v-form"><label>CS2 路径<input v-model="settings.cs2_path"></label><label>FFmpeg 路径<input v-model="settings.ffmpeg_path"></label><label>编码器<select v-model="settings.montage_encoder"><option value="auto">自动</option><option value="libx264">libx264</option><option value="h264_nvenc">NVENC</option></select></label><label><input type="checkbox" v-model="settings.ai_mode"> AI 点评</label><label><input type="checkbox" v-model="settings.obs_transition_enabled"> OBS 转场</label><label>转场名称<input v-model="settings.obs_transition_name"></label><label>转场时长 ms<input type="number" v-model.number="settings.obs_transition_duration_ms"></label><label><input type="checkbox" v-model="settings.kb_overlay_enabled"> 键盘轨迹</label><label>键盘 Tick 偏移<input type="number" v-model.number="settings.kb_overlay_tick_offset"></label><label><input type="checkbox" v-model="settings.kill_fx_enabled"> 击杀特效</label><label>击杀特效 Tick 偏移<input type="number" v-model.number="settings.kill_fx_tick_offset"></label></div><div class="cs2v-actions"><button class="btn-sm" @click="settingsOpen=false">取消</button><button class="btn-sm success" :disabled="loading" @click="saveSettings">保存</button></div></div>
      <div class="cs2v-steps"><div v-for="(x,i) in ['玩家','对局','片段','输出']" class="cs2v-step" :class="{active:step===i+1}"><b>{{i+1}}</b> {{x}}</div></div>
      <div v-if="error" class="cs2v-error" style="margin-bottom:12px">{{error}}</div>
      <div v-if="step===1"><div class="cs2v-grid"><button v-for="p in boot.players" class="cs2v-option cs2v-player" @click="choosePlayer(p)"><img v-if="p.avatar" :src="p.avatar" class="cs2v-avatar"><span><div class="cs2v-title">{{p.nickname}}</div><div class="cs2v-muted">{{p.steamid}}</div></span></button></div><div v-if="!boot.players.length" class="cs2v-muted">没有可用玩家</div></div>
      <div v-if="step===2"><div class="cs2v-muted" v-if="query&&query.status==='querying'">正在查询最近 10 场对局...</div><div class="cs2v-grid cs2v-match-grid"><button v-for="m in matches" class="cs2v-option cs2v-match" :class="{selected:selectedMatch===m}" @click="selectedMatch=m"><div class="cs2v-title">{{m.map||'平台未返回地图'}} · {{m.score||'平台未返回比分'}}</div><div class="cs2v-muted">{{m.played_at||''}} · {{m.result||(m.is_mvp?'MVP':'平台未返回赛果')}}</div><div class="cs2v-match-stats"><span>K/D/A <b>{{stat(m.stats&&m.stats.kills)}} / {{stat(m.stats&&m.stats.deaths)}} / {{stat(m.stats&&m.stats.assists)}}</b></span><span>RT <b>{{stat(m.stats&&m.stats.rating,2)}}</b> · PW RT <b>{{stat(m.stats&&m.stats.pw_rating,2)}}</b></span><span>WE <b>{{stat(m.stats&&m.stats.we,1)}}</b></span></div><div class="cs2v-muted"><span v-if="m.ladder_score!==null&&m.ladder_score!==undefined">天梯分 {{m.ladder_score}} <span v-if="signed(m.ladder_change)">({{signed(m.ladder_change)}})</span></span><span v-if="m.duration_minutes!==null&&m.duration_minutes!==undefined"> · {{m.duration_minutes}} 分钟</span> · {{m.demo_available===true?'Demo 可用':m.demo_available===false?'Demo 不可用':'Demo 将在下载时验证'}}</div></button></div><div class="cs2v-actions"><button class="btn-sm" @click="step=1">上一步</button><button class="btn-sm success" :disabled="!selectedMatch||loading||!query||query.status!=='completed'" @click="createJob">下载并分析</button></div></div>
      <div v-if="step===3"><div v-if="!job||job.status!=='awaiting_clip_selection'" class="cs2v-muted">{{job ? '当前阶段：'+job.status+'（'+job.progress+'%）' : '等待任务创建'}}</div><template v-else><div class="cs2v-events"><label v-for="e in job.events" class="cs2v-event cs2v-event-detail"><input type="checkbox" :checked="selected.includes(e.event_key)" @change="toggle(e.event_key)"><b>第 {{e.round}} 回合</b><span><b>{{e.category}} · {{e.kills||0}} 杀 · {{e.weapon||''}}</b><small>受害者：{{(e.victims||[]).join('、')||'--'}} · 标签：{{(e.tags||[]).join('、')||'--'}} · 比分：{{e.score_own??'--'}} : {{e.score_opp??'--'}} · {{e.round_won===true?'本回合胜利':e.round_won===false?'本回合失利':'回合结果未知'}} · Tick {{e.start_tick}}-{{e.end_tick}}</small><small v-if="e.source_rounds&&e.source_rounds.length">来源回合：{{e.source_rounds.join('、')}}</small></span><span class="cs2v-muted">{{e.comment||''}}</span></label></div><div class="cs2v-actions"><button class="btn-sm success" :disabled="!selected.length" @click="step=4">确认片段</button></div></template></div>
      <div v-if="step===4"><div class="cs2v-form"><label>画面预设<select v-model="output.preset_id"><option v-for="p in boot.presets" :value="p.id">{{p.label}}</option></select></label><label>包装<select v-model="output.packaging_id"><option v-for="p in boot.packaging_presets" :value="p.id">{{p.label}}</option></select></label><label>BGM<select v-model="output.bgm_id"><option v-for="p in boot.bgm_presets" :value="p.id">{{p.label}}</option></select></label><label>微信接收目标<select v-model="output.wechat_target"><option value="" disabled>请选择</option><option v-for="t in boot.wechat_targets" :value="targetValue(t)">{{targetLabel(t)}}</option></select></label></div><div class="cs2v-actions"><button class="btn-sm" @click="step=3">上一步</button><button class="btn-sm success" :disabled="!job||!selected.length||!output.wechat_target||loading" @click="submit">开始制作并发送</button></div></div>
      <div class="cs2v-panel"><h3>任务中心</h3><div v-if="!jobs.length" class="cs2v-muted">暂无任务</div><div v-for="j in jobs" class="cs2v-job"><div><b>{{j.match_id}}</b><div class="cs2v-muted">{{j.status}}</div></div><div><div class="cs2v-progress"><i :style="{width:j.progress+'%'}"></i></div><div v-if="j.error" class="cs2v-error">{{j.error}}</div></div><div><button v-if="!['completed','cancelled'].includes(j.status)" class="btn-sm" @click="action(j.id,'cancel')">取消</button><button v-if="['failed','sending_unknown'].includes(j.status)" class="btn-sm" @click="action(j.id,'retry')">重试</button></div></div></div>
    </section>`
  };
})();
