(() => {
  const app = document.getElementById('quiz-app');
  if (!app) return;

  const form = document.getElementById('quiz-form');
  const timerNode = document.getElementById('timer');
  const fill = document.getElementById('progress-fill');
  const answeredNode = document.getElementById('answered-count');
  const overlay = document.getElementById('start-overlay');
  const beginButton = document.getElementById('begin-test');
  const toast = document.getElementById('violation-toast');
  const attemptId = app.dataset.attemptId;
  const violationLimit = Number(app.dataset.violationLimit || 3);

  let secondsLeft = Number(app.dataset.remaining || 0);
  let started = false;
  let submitting = false;
  let lastViolationAt = 0;
  let toastTimer = null;

  const updateProgress = () => {
    const total = form.querySelectorAll('.question-card').length;
    const answered = form.querySelectorAll('input[type="radio"]:checked').length;
    answeredNode.textContent = `${answered} из ${total} отвечено`;
    fill.style.width = `${total ? (answered / total) * 100 : 0}%`;
  };

  form.addEventListener('change', (event) => {
    if (event.target.matches('input[type="radio"]')) updateProgress();
  });
  updateProgress();

  const renderTimer = () => {
    const minutes = Math.floor(secondsLeft / 60).toString().padStart(2, '0');
    const seconds = (secondsLeft % 60).toString().padStart(2, '0');
    timerNode.textContent = `${minutes}:${seconds}`;
    if (secondsLeft <= 60) timerNode.parentElement.classList.add('timer-warning');
  };
  renderTimer();

  const submitTest = () => {
    if (submitting) return;
    submitting = true;
    form.submit();
  };

  beginButton.addEventListener('click', async () => {
    started = true;
    overlay.remove();
    if (document.documentElement.requestFullscreen) {
      try { await document.documentElement.requestFullscreen(); }
      catch (_error) { showToast('Полноэкранный режим недоступен. Не переключайте вкладки.'); }
    }
  });

  const interval = window.setInterval(() => {
    if (submitting) return;
    secondsLeft -= 1;
    renderTimer();
    if (secondsLeft <= 0) {
      window.clearInterval(interval);
      submitTest();
    }
  }, 1000);

  const showToast = (message) => {
    toast.textContent = message;
    toast.classList.add('visible');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove('visible'), 3400);
  };

  const recordViolation = async (eventType) => {
    if (!started || submitting) return;
    const now = Date.now();
    if (now - lastViolationAt < 1400) return;
    lastViolationAt = now;

    const currentAnswers = {};
    new FormData(form).forEach((value, key) => { currentAnswers[key] = value; });
    try {
      const response = await fetch(`/quiz/${attemptId}/violation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_type: eventType, answers: currentAnswers }),
        keepalive: true
      });
      if (!response.ok) return;
      const data = await response.json();
      if (data.disqualified || data.status === 'closed') {
        submitting = true;
        window.location.assign(data.redirect || `/result/${attemptId}`);
        return;
      }
      showToast(`Зафиксировано нарушение: ${data.violations} из ${violationLimit}. При следующем выходе тест завершится.`);
    } catch (_error) {
      showToast('Не удалось отправить отметку о потере фокуса. Проверьте соединение.');
    }
  };

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) recordViolation('tab_hidden');
  });
  window.addEventListener('blur', () => recordViolation('window_blur'));
  document.addEventListener('fullscreenchange', () => {
    if (started && !document.fullscreenElement) recordViolation('fullscreen_exit');
  });

  // Reduce casual copying during a supervised attempt. This is deterrence, not a security boundary.
  ['copy', 'cut', 'paste', 'contextmenu'].forEach((eventName) => {
    document.addEventListener(eventName, (event) => {
      if (started) event.preventDefault();
    });
  });

  form.addEventListener('submit', () => { submitting = true; });
  window.addEventListener('beforeunload', (event) => {
    if (started && !submitting) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
})();
