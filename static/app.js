// ZeroSyN Synthetic Future Terminal Client
(function () {
  'use strict';

  // State
  const state = {
    symbol: 'NIFTY',
    expiry: null,
    strikeMode: 'auto', // 'auto' or 'manual'
    selectedStrike: null,
    calcMode: 'ltp', // 'ltp' or 'mid'
    interval: '1s',
    chartType: 'candle', // 'candle' or 'line'
    showSpotOverlay: true,
    soundEnabled: false,
    theme: localStorage.getItem('zerosyn_theme') || 'dark',
    lastSynPrice: null,
    ws: null,
    isConnected: false,
  };

  // DOM Elements
  const el = {
    synPrice: document.getElementById('syn-price'),
    spotPrice: document.getElementById('spot-price'),
    basisPrice: document.getElementById('basis-price'),
    basisStateTag: document.getElementById('basis-state-tag'),
    basisPct: document.getElementById('basis-percentage'),
    activeStrikeBadge: document.getElementById('active-strike-badge'),
    strikeTag: document.getElementById('strike-tag'),
    cePrice: document.getElementById('ce-price'),
    pePrice: document.getElementById('pe-price'),
    straddlePrice: document.getElementById('straddle-price'),
    parityBreakdown: document.getElementById('parity-breakdown'),
    feedTimestamp: document.getElementById('feed-timestamp'),
    sourceBadge: document.getElementById('source-badge'),
    latencyVal: document.getElementById('latency-val'),
    statStrikes: document.getElementById('stat-strikes'),
    statSource: document.getElementById('stat-source'),
    expirySelect: document.getElementById('expiry-select'),
    strikeSelect: document.getElementById('strike-select'),
    atmLockBtn: document.getElementById('atm-lock-btn'),
    resetAtmBtn: document.getElementById('reset-atm-btn'),
    spotOverlayChk: document.getElementById('spot-overlay-chk'),
    spotLegend: document.getElementById('spot-legend'),
    soundBtn: document.getElementById('sound-btn'),
    soundIconOn: document.getElementById('sound-icon-on'),
    soundIconOff: document.getElementById('sound-icon-off'),
    themeBtn: document.getElementById('theme-btn'),
    themeIconSun: document.getElementById('theme-icon-sun'),
    themeIconMoon: document.getElementById('theme-icon-moon'),
    tickAudio: document.getElementById('tick-audio'),
    matrixTbody: document.getElementById('matrix-tbody'),
    chartInstrumentTitle: document.getElementById('chart-instrument-title'),
    chartTfTitle: document.getElementById('chart-tf-title'),
    spotSymbolTag: document.getElementById('spot-symbol-tag'),
    chartContainer: document.getElementById('tv-chart-container'),
    metricsBarSection: document.getElementById('metrics-bar-section'),
    toggleMetricsBtn: document.getElementById('toggle-metrics-btn'),
    toggleChainBtn: document.getElementById('toggle-chain-btn'),
    hideChainDockBtn: document.getElementById('hide-chain-dock-btn'),
    chartShowChainBtn: document.getElementById('chart-show-chain-btn'),
    matrixPanel: document.querySelector('.matrix-panel'),
  };

  // Audio Context synthesizer for high-performance tick sounds
  let audioCtx = null;
  function playTickSound(isUp) {
    if (!state.soundEnabled) return;
    try {
      if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(isUp ? 880 : 440, audioCtx.currentTime);
      gain.gain.setValueAtTime(0.04, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.05);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.05);
    } catch (e) {
      // Ignore audio errors
    }
  }

  // TradingView Lightweight Charts Setup
  let chart = null;
  let candleSeries = null;
  let lineSeries = null;
  let spotSeries = null;

  function initCharts() {
    const isLight = state.theme === 'light';
    const chartOptions = {
      layout: {
        background: { color: isLight ? '#ffffff' : '#030712' },
        textColor: isLight ? '#475569' : '#64748b',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: isLight ? '#f1f5f9' : '#0b1329' },
        horzLines: { color: isLight ? '#f1f5f9' : '#0b1329' },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
        vertLine: { color: isLight ? '#0284c7' : '#38bdf8', width: 1, style: 3 },
        horzLine: { color: isLight ? '#0284c7' : '#38bdf8', width: 1, style: 3 },
      },
      rightPriceScale: {
        borderColor: isLight ? '#cbd5e1' : '#1f293d',
        autoScale: true,
      },
      timeScale: {
        borderColor: isLight ? '#cbd5e1' : '#1f293d',
        timeVisible: true,
        secondsVisible: true,
      },
    };

    // Main Chart (Fills entire container)
    chart = LightweightCharts.createChart(el.chartContainer, {
      ...chartOptions,
      height: el.chartContainer.clientHeight || 360,
    });

    // Candlestick Series
    candleSeries = chart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#f43f5e',
      borderUpColor: '#10b981',
      borderDownColor: '#f43f5e',
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    });

    // Line / Area Series
    lineSeries = chart.addAreaSeries({
      topColor: isLight ? 'rgba(2, 132, 199, 0.25)' : 'rgba(56, 189, 248, 0.35)',
      bottomColor: 'rgba(56, 189, 248, 0.0)',
      lineColor: isLight ? '#0284c7' : '#38bdf8',
      lineWidth: 2,
      visible: false,
    });

    // Spot Overlay Series (Dashed Amber)
    spotSeries = chart.addLineSeries({
      color: isLight ? '#d97706' : '#f59e0b',
      lineWidth: 1,
      lineStyle: 2, // Dashed
      priceLineVisible: false,
      visible: state.showSpotOverlay,
    });

    // Resize observer
    window.addEventListener('resize', () => {
      if (chart && el.chartContainer) {
        chart.applyOptions({
          width: el.chartContainer.clientWidth,
          height: el.chartContainer.clientHeight,
        });
      }
    });
  }

  function applyTheme(theme) {
    state.theme = theme;
    const isLight = theme === 'light';
    document.body.className = isLight ? 'light-theme' : 'dark-theme';

    if (el.themeIconSun && el.themeIconMoon) {
      if (isLight) {
        el.themeIconSun.classList.add('hidden');
        el.themeIconMoon.classList.remove('hidden');
      } else {
        el.themeIconSun.classList.remove('hidden');
        el.themeIconMoon.classList.add('hidden');
      }
    }

    try {
      localStorage.setItem('zerosyn_theme', theme);
    } catch (e) {
      // localStorage fallback
    }

    if (chart) {
      chart.applyOptions({
        layout: {
          background: { color: isLight ? '#ffffff' : '#030712' },
          textColor: isLight ? '#475569' : '#64748b',
        },
        grid: {
          vertLines: { color: isLight ? '#f1f5f9' : '#0b1329' },
          horzLines: { color: isLight ? '#f1f5f9' : '#0b1329' },
        },
        crosshair: {
          vertLine: { color: isLight ? '#0284c7' : '#38bdf8' },
          horzLine: { color: isLight ? '#0284c7' : '#38bdf8' },
        },
        rightPriceScale: {
          borderColor: isLight ? '#cbd5e1' : '#1f293d',
        },
        timeScale: {
          borderColor: isLight ? '#cbd5e1' : '#1f293d',
        },
      });

      if (lineSeries) {
        lineSeries.applyOptions({
          topColor: isLight ? 'rgba(2, 132, 199, 0.25)' : 'rgba(56, 189, 248, 0.35)',
          lineColor: isLight ? '#0284c7' : '#38bdf8',
        });
      }

      if (spotSeries) {
        spotSeries.applyOptions({
          color: isLight ? '#d97706' : '#f59e0b',
        });
      }
    }
  }

  // WebSocket Connection
  function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    el.sourceBadge.textContent = 'CONNECTING';
    el.sourceBadge.className = 'text-dim';

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      state.isConnected = true;
      el.sourceBadge.textContent = 'LIVE';
      el.sourceBadge.className = 'text-green';
    };

    state.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'SNAPSHOT') {
          handleSnapshot(msg);
        } else if (msg.type === 'TICK') {
          handleTick(msg);
        }
      } catch (err) {
        console.error('Error processing websocket message:', err);
      }
    };

    state.ws.onclose = () => {
      state.isConnected = false;
      el.sourceBadge.textContent = 'RECONNECTING';
      el.sourceBadge.className = 'text-red';
      setTimeout(connectWebSocket, 2000);
    };

    state.ws.onerror = (err) => {
      console.error('WebSocket error:', err);
      state.ws.close();
    };
  }

  function sendConfig() {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({
        type: 'SET_CONFIG',
        symbol: state.symbol,
        expiry: state.expiry,
        strike: state.strikeMode === 'auto' ? 'auto' : state.selectedStrike,
        calc_mode: state.calcMode,
        interval: state.interval,
      }));
    }
  }

  // Handlers
  function handleSnapshot(data) {
    const syn = data.synthetic || {};
    const history = data.history || [];

    // Update Expiries Dropdown
    updateExpiries(syn.all_expiries || [], syn.expiry);

    // Update Strikes Dropdown
    updateStrikes(syn.all_strikes || [], syn.selected_strike, syn.atm_strike);

    // Load Charts History
    if (history.length > 0) {
      const candleBars = [];
      const lineBars = [];
      const spotBars = [];

      history.forEach((bar) => {
        candleBars.push({
          time: bar.time,
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        });
        lineBars.push({
          time: bar.time,
          value: bar.close,
        });
        spotBars.push({
          time: bar.time,
          value: bar.spot,
        });
      });

      candleSeries.setData(candleBars);
      lineSeries.setData(lineBars);
      spotSeries.setData(spotBars);

      chart.timeScale().fitContent();
    }

    renderSyntheticMetrics(syn);
    renderMatrixTable(syn.strike_matrix || [], syn.spot);
  }

  function handleTick(data) {
    const syn = data.synthetic || {};
    const bar = data.bar;

    if (bar) {
      candleSeries.update({
        time: bar.time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      });
      lineSeries.update({
        time: bar.time,
        value: bar.close,
      });
      spotSeries.update({
        time: bar.time,
        value: bar.spot,
      });
    }

    // Tick audio and flash
    const currentPrice = syn.synthetic_future;
    if (state.lastSynPrice !== null && currentPrice !== state.lastSynPrice) {
      const isUp = currentPrice > state.lastSynPrice;
      flashHeroPrice(isUp);
      playTickSound(isUp);
    }
    state.lastSynPrice = currentPrice;

    renderSyntheticMetrics(syn);
    renderMatrixTable(syn.strike_matrix || [], syn.spot);
  }

  function flashHeroPrice(isUp) {
    el.synPrice.classList.remove('flash-up', 'flash-down');
    void el.synPrice.offsetWidth; // trigger reflow
    el.synPrice.classList.add(isUp ? 'flash-up' : 'flash-down');
    setTimeout(() => {
      el.synPrice.classList.remove('flash-up', 'flash-down');
    }, 400);
  }

  function renderSyntheticMetrics(syn) {
    el.synPrice.textContent = syn.synthetic_future ? syn.synthetic_future.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '--.--';
    el.spotPrice.textContent = syn.spot ? syn.spot.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '--.--';
    
    // Basis (Synthetic Future - Spot)
    const basis = syn.basis !== undefined ? syn.basis : 0.0;
    const basisSign = basis >= 0 ? '+' : '';
    el.basisPrice.textContent = `${basisSign}${basis.toFixed(2)}`;
    el.basisPrice.className = `metric-price mono ${basis >= 0 ? 'text-green' : 'text-red'}`;
    el.basisStateTag.textContent = basis >= 0 ? 'PREMIUM' : 'DISCOUNT';
    el.basisStateTag.className = `metric-tag ${basis >= 0 ? 'text-green' : 'text-red'}`;

    const basisPct = syn.spot > 0 ? (basis / syn.spot) * 100 : 0.0;
    el.basisPct.textContent = `${basisSign}${basisPct.toFixed(2)}%`;
    el.basisPct.className = `sub-val mono ${basis >= 0 ? 'text-green' : 'text-red'}`;

    // Active Strike & Legs
    const strike = syn.selected_strike || syn.atm_strike;
    el.activeStrikeBadge.textContent = strike ? strike.toLocaleString('en-IN') : '--';
    el.strikeTag.textContent = syn.selected_strike === syn.atm_strike ? 'ATM' : 'CUSTOM';
    el.strikeTag.className = `metric-tag ${syn.selected_strike === syn.atm_strike ? 'formula-badge' : ''}`;

    el.cePrice.textContent = syn.call_price ? `₹${syn.call_price.toFixed(2)}` : '--';
    el.pePrice.textContent = syn.put_price ? `₹${syn.put_price.toFixed(2)}` : '--';
    const straddle = (syn.call_price || 0) + (syn.put_price || 0);
    el.straddlePrice.textContent = straddle > 0 ? `₹${straddle.toFixed(2)}` : '--';

    // Parity breakdown equation: Strike + Call - Put
    el.parityBreakdown.textContent = `${strike} + ${syn.call_price?.toFixed(1) || 0} − ${syn.put_price?.toFixed(1) || 0} = ${syn.synthetic_future || 0}`;

    // Source and timestamp
    el.feedTimestamp.textContent = syn.timestamp ? syn.timestamp.split(' ')[1] || syn.timestamp : '--:--:--';
    if (syn.source) {
      el.sourceBadge.textContent = syn.source.replace('_', ' ');
      el.statSource.textContent = syn.source.replace('_', ' ');
    }
    el.statStrikes.textContent = (syn.all_strikes || []).length;
    el.spotSymbolTag.textContent = state.symbol;
    const activeExpiry = syn.expiry || state.expiry || '';
    el.chartInstrumentTitle.textContent = `${state.symbol} SYNTHETIC FUTURE ${activeExpiry ? `[${activeExpiry}]` : ''} (${strike})`;
  }

  function updateExpiries(expiries, currentExpiry) {
    if (!expiries || expiries.length === 0) return;

    const existingOptions = Array.from(el.expirySelect.options).map(o => o.value);
    const isDifferent = existingOptions.length !== expiries.length || !expiries.every((exp, i) => exp === existingOptions[i]);

    if (isDifferent) {
      el.expirySelect.innerHTML = '';
      expiries.forEach((exp) => {
        const opt = document.createElement('option');
        opt.value = exp;
        opt.textContent = exp;
        el.expirySelect.appendChild(opt);
      });
    }

    // Preserve the user's selected expiry if available in expiries, otherwise use currentExpiry from server
    const selectExp = (state.expiry && expiries.includes(state.expiry))
      ? state.expiry
      : (currentExpiry && expiries.includes(currentExpiry) ? currentExpiry : expiries[0]);

    el.expirySelect.value = selectExp;
    state.expiry = selectExp;
  }

  function updateStrikes(strikes, selectedStrike, atmStrike) {
    if (!strikes || strikes.length === 0) return;
    el.strikeSelect.innerHTML = '';
    
    // Auto ATM option
    const autoOpt = document.createElement('option');
    autoOpt.value = 'auto';
    autoOpt.textContent = `ATM (${atmStrike ? atmStrike.toLocaleString('en-IN') : 'Auto'})`;
    el.strikeSelect.appendChild(autoOpt);

    strikes.forEach((k) => {
      const opt = document.createElement('option');
      opt.value = k;
      opt.textContent = `${k.toLocaleString('en-IN')}${k === atmStrike ? ' (ATM)' : ''}`;
      el.strikeSelect.appendChild(opt);
    });

    if (state.strikeMode === 'auto') {
      el.strikeSelect.value = 'auto';
      el.strikeSelect.disabled = true;
      el.atmLockBtn.classList.add('active');
    } else {
      el.strikeSelect.value = selectedStrike || strikes[0];
      el.strikeSelect.disabled = false;
      el.atmLockBtn.classList.remove('active');
    }
  }

  function renderMatrixTable(matrix, spot) {
    if (!matrix || matrix.length === 0) {
      el.matrixTbody.innerHTML = '<tr><td colspan="7" class="text-center py-4">No strike data available</td></tr>';
      return;
    }

    let html = '';
    matrix.forEach((row) => {
      const rowClass = row.is_selected ? 'selected-row' : (row.is_atm ? 'atm-row' : '');
      const badgeClass = row.is_atm ? 'strike-badge atm-badge' : 'strike-badge';
      const basisClass = row.basis >= 0 ? 'text-green' : 'text-red';
      const basisSign = row.basis >= 0 ? '+' : '';

      const formatOI = (oi) => {
        if (!oi) return '-';
        if (oi >= 100000) return (oi / 1000).toFixed(0) + 'k';
        if (oi >= 10000) return (oi / 1000).toFixed(1) + 'k';
        return oi.toLocaleString('en-IN');
      };

      html += `
        <tr class="${rowClass}" data-strike="${row.strike}">
          <td class="align-right text-dim">${formatOI(row.ce_oi)}</td>
          <td class="align-right text-green font-bold">${row.ce_ltp ? row.ce_ltp.toFixed(2) : '-'}</td>
          <td class="strike-col"><span class="${badgeClass}">${row.strike.toLocaleString('en-IN')}${row.is_atm ? ' ATM' : ''}</span></td>
          <td class="align-left text-red font-bold">${row.pe_ltp ? row.pe_ltp.toFixed(2) : '-'}</td>
          <td class="align-left text-dim">${formatOI(row.pe_oi)}</td>
          <td class="align-right font-bold text-main">${row.synthetic_future ? row.synthetic_future.toFixed(2) : '-'}</td>
          <td class="align-right font-bold ${basisClass}">${row.basis ? `${basisSign}${row.basis.toFixed(2)}` : '-'}</td>
        </tr>
      `;
    });
    el.matrixTbody.innerHTML = html;

    // Attach click listener to row to lock strike
    el.matrixTbody.querySelectorAll('tr[data-strike]').forEach((tr) => {
      tr.addEventListener('click', () => {
        const strike = parseFloat(tr.getAttribute('data-strike'));
        setStrike(strike);
      });
    });
  }

  function setStrike(strike) {
    state.strikeMode = 'manual';
    state.selectedStrike = strike;
    el.strikeSelect.value = strike;
    el.strikeSelect.disabled = false;
    el.atmLockBtn.classList.remove('active');
    sendConfig();
  }

  function setAutoATM() {
    state.strikeMode = 'auto';
    state.selectedStrike = null;
    el.strikeSelect.value = 'auto';
    el.strikeSelect.disabled = true;
    el.atmLockBtn.classList.add('active');
    sendConfig();
  }

  // Event Listeners
  function attachEvents() {
    // Index selector buttons
    document.querySelectorAll('.index-selector .segment-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.index-selector .segment-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.symbol = btn.getAttribute('data-symbol');
        state.expiry = null;
        state.strikeMode = 'auto';
        sendConfig();
      });
    });

    // Expiry dropdown
    el.expirySelect.addEventListener('change', () => {
      state.expiry = el.expirySelect.value;
      state.selectedStrike = null;
      state.strikeMode = 'auto';
      sendConfig();
    });

    // Strike dropdown
    el.strikeSelect.addEventListener('change', () => {
      const val = el.strikeSelect.value;
      if (val === 'auto') {
        setAutoATM();
      } else {
        setStrike(parseFloat(val));
      }
    });

    // Auto ATM Lock button
    el.atmLockBtn.addEventListener('click', () => {
      if (state.strikeMode === 'auto') {
        // Unlock to current value
        state.strikeMode = 'manual';
        el.strikeSelect.disabled = false;
        el.atmLockBtn.classList.remove('active');
      } else {
        setAutoATM();
      }
    });

    el.resetAtmBtn.addEventListener('click', setAutoATM);

    // Calc mode selector (LTP / MID)
    document.querySelectorAll('.mode-selector .segment-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.mode-selector .segment-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.calcMode = btn.getAttribute('data-calc');
        sendConfig();
      });
    });

    // Interval selector (1s, 5s, 1m, Line)
    document.querySelectorAll('.interval-selector .segment-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.interval-selector .segment-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');

        const interval = btn.getAttribute('data-interval');
        const type = btn.getAttribute('data-type');

        if (type === 'line') {
          state.chartType = 'line';
          candleSeries.applyOptions({ visible: false });
          lineSeries.applyOptions({ visible: true });
          el.chartTfTitle.textContent = 'Line / Area';
        } else if (interval) {
          state.interval = interval;
          state.chartType = 'candle';
          candleSeries.applyOptions({ visible: true });
          lineSeries.applyOptions({ visible: false });
          el.chartTfTitle.textContent = `${interval} Candles`;
          sendConfig();
        }
      });
    });

    // Spot overlay checkbox
    el.spotOverlayChk.addEventListener('change', () => {
      state.showSpotOverlay = el.spotOverlayChk.checked;
      spotSeries.applyOptions({ visible: state.showSpotOverlay });
      el.spotLegend.style.display = state.showSpotOverlay ? 'flex' : 'none';
    });

    // Sound toggle button
    el.soundBtn.addEventListener('click', () => {
      state.soundEnabled = !state.soundEnabled;
      if (state.soundEnabled) {
        el.soundIconOn.classList.remove('hidden');
        el.soundIconOff.classList.add('hidden');
        playTickSound(true);
      } else {
        el.soundIconOn.classList.add('hidden');
        el.soundIconOff.classList.remove('hidden');
      }
    });

    // Theme toggle button
    if (el.themeBtn) {
      el.themeBtn.addEventListener('click', () => {
        const nextTheme = state.theme === 'light' ? 'dark' : 'light';
        applyTheme(nextTheme);
      });
    }

    // Toggle Metrics Cards visibility
    if (el.toggleMetricsBtn && el.metricsBarSection) {
      el.toggleMetricsBtn.addEventListener('click', () => {
        const isCollapsed = el.metricsBarSection.classList.toggle('collapsed');
        el.toggleMetricsBtn.textContent = isCollapsed ? 'Show Cards' : 'Hide Cards';
        setTimeout(() => {
          if (chart && el.chartContainer) {
            chart.applyOptions({
              width: el.chartContainer.clientWidth,
              height: el.chartContainer.clientHeight,
            });
          }
        }, 50);
      });
    }

    // Toggle Option Chain visibility
    if (el.toggleChainBtn) {
      el.toggleChainBtn.addEventListener('click', () => toggleOptionChain());
    }
    if (el.hideChainDockBtn) {
      el.hideChainDockBtn.addEventListener('click', () => toggleOptionChain(false));
    }
    if (el.chartShowChainBtn) {
      el.chartShowChainBtn.addEventListener('click', () => toggleOptionChain(true));
    }
  }

  function toggleOptionChain(visible) {
    if (!el.matrixPanel) {
      el.matrixPanel = document.querySelector('.matrix-panel');
    }
    if (!el.matrixPanel) return;

    const isHidden = typeof visible === 'boolean'
      ? !visible
      : !el.matrixPanel.classList.contains('collapsed');

    el.matrixPanel.classList.toggle('collapsed', isHidden);

    const btnText = isHidden ? 'Show Option Chain' : 'Hide Option Chain';
    if (el.toggleChainBtn) {
      el.toggleChainBtn.textContent = btnText;
      el.toggleChainBtn.title = isHidden ? 'Show Option Chain' : 'Hide Option Chain';
    }

    if (el.chartShowChainBtn) {
      if (isHidden) {
        el.chartShowChainBtn.classList.remove('hidden');
      } else {
        el.chartShowChainBtn.classList.add('hidden');
      }
    }

    try {
      localStorage.setItem('zerosyn_hide_chain', isHidden ? '1' : '0');
    } catch (e) {}

    setTimeout(() => {
      if (chart && el.chartContainer) {
        chart.applyOptions({
          width: el.chartContainer.clientWidth,
          height: el.chartContainer.clientHeight,
        });
        chart.timeScale().fitContent();
      }
    }, 50);
  }

  // Initialization
  window.addEventListener('DOMContentLoaded', () => {
    initCharts();
    applyTheme(state.theme);
    attachEvents();
    try {
      if (localStorage.getItem('zerosyn_hide_chain') === '1') {
        toggleOptionChain(false);
      }
    } catch (e) {}
    connectWebSocket();
  });
})();
