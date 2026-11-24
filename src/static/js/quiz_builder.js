(() => {
  const container = document.getElementById('questions-container');
  const template = document.getElementById('question-template');
  const addButton = document.getElementById('add-question');
  const countLabel = document.getElementById('question-count');
  if (!container || !template || !addButton) return;

  const maxQuestions = 30;

  function updateQuestions() {
    const cards = [...container.querySelectorAll('.question-builder-card')];
    cards.forEach((card, index) => {
      const number = card.querySelector('.builder-question-number');
      if (number) number.textContent = `Вопрос ${index + 1}`;
    });
    countLabel.textContent = `${cards.length} ${cards.length === 1 ? 'вопрос' : cards.length < 5 ? 'вопроса' : 'вопросов'}`;
    addButton.disabled = cards.length >= maxQuestions;
    addButton.textContent = cards.length >= maxQuestions ? 'Достигнут лимит вопросов' : '＋ Добавить вопрос';
  }

  addButton.addEventListener('click', () => {
    if (container.querySelectorAll('.question-builder-card').length >= maxQuestions) return;
    container.appendChild(template.content.cloneNode(true));
    updateQuestions();
    container.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });

  container.addEventListener('click', (event) => {
    const removeButton = event.target.closest('.remove-question');
    if (!removeButton) return;
    const cards = container.querySelectorAll('.question-builder-card');
    if (cards.length <= 1) return;
    removeButton.closest('.question-builder-card').remove();
    updateQuestions();
  });

  document.getElementById('quiz-builder-form')?.addEventListener('submit', (event) => {
    const cards = container.querySelectorAll('.question-builder-card');
    if (!cards.length || cards.length > maxQuestions) {
      event.preventDefault();
      window.alert('Добавьте от 1 до 30 вопросов.');
    }
  });

  updateQuestions();
})();
