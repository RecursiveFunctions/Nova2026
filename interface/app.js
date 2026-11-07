'use strict';

// Customer-only prototype. No request is sent to the backend yet.
const app = document.querySelector('#app');
const params = new URLSearchParams(window.location.search);

const state = {
  orderId: params.get('order') || '1042',
  isDemoOrder: !params.get('order'),
  page: 'order',
  received: false,
  category: '',
  description: '',
  photoUrl: null,
  photoName: '',
  error: '',
  savedReport: null
};

const categories = [
  'This isn’t my order',
  'An item is missing',
  'An item is incorrect',
  'Food quality',
  'Something else'
];

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[character]);
}

function button(label, action, secondary = false) {
  return `
    <button
      type="button"
      class="${secondary ? 'secondary' : 'primary'}"
      data-action="${action}"
    >
      ${label}
    </button>
  `;
}

function orderCard() {
  return `
    <article class="order">
      <div class="order-top">
        <strong>#${escapeHtml(state.orderId)}</strong>
        <span class="pill">
          ${state.received ? 'Receipt confirmed · demo' : 'Awaiting receipt · demo'}
        </span>
      </div>
      ${state.isDemoOrder ? `
        <div class="meta">
          Green Bowl Kitchen · sample order<br>
          1 × Harvest bowl · 1 × Iced tea
        </div>
      ` : `
        <p class="meta">Order details require a backend connection.</p>
      `}
    </article>
  `;
}

function reportForm() {
  return `
    <button type="button" class="back" data-action="categories">
      ← Problem type
    </button>
    <h1 id="page-title" tabindex="-1">Report a problem</h1>
    <p>${escapeHtml(state.category)}</p>

    <form id="report-form">
      <label for="description">What happened?</label>
      <textarea
        id="description"
        name="description"
        maxlength="2000"
        placeholder="Describe the problem with your order."
        required
      >${escapeHtml(state.description)}</textarea>

      <label class="file" for="photo">
        Add a photo · optional
        <input id="photo" name="photo" type="file" accept="image/*">
      </label>

      ${state.photoUrl ? `
        <img class="photo" src="${escapeHtml(state.photoUrl)}" alt="Selected problem photo">
        <p class="meta">${escapeHtml(state.photoName)}</p>
        ${button('Remove photo', 'remove-photo', true)}
      ` : ''}

      <p id="form-error" role="alert">${escapeHtml(state.error)}</p>
      <p class="notice">
        Demo only. Your report and photo stay in this tab and are not sent.
      </p>
      <button class="primary" type="submit">Save demo report</button>
    </form>
  `;
}

function render(focusHeading = false) {
  let content = '';

  if (state.page === 'order') {
    content = `
      <span class="eyebrow">CUSTOMER</span>
      <h1 id="page-title" tabindex="-1">Your order</h1>
      <p>Check your items before confirming receipt.</p>
      ${orderCard()}
      ${state.received ? `
        <p class="notice" role="status">Receipt confirmed in this demo.</p>
      ` : button('Confirm received', 'confirm-receipt')}
      ${button('Report a problem', 'categories', true)}
      ${state.savedReport ? button('View saved demo report', 'saved', true) : ''}
      <p class="demo">Prototype · no confirmation or report is sent to the restaurant.</p>
    `;
  } else if (state.page === 'confirm') {
    content = `
      <button type="button" class="back" data-action="order">← Order</button>
      <h1 id="page-title" tabindex="-1">Received your order?</h1>
      ${orderCard()}
      <p>Confirm that the delivery was handed to you. You can still report a problem afterward.</p>
      ${button('Yes, confirm receipt · demo', 'receive')}
      ${button('Go back', 'order', true)}
    `;
  } else if (state.page === 'received') {
    content = `
      <div class="status" aria-hidden="true">✓</div>
      <h1 id="page-title" tabindex="-1">Receipt confirmed</h1>
      <p>Recorded in this demo only.</p>
      ${orderCard()}
      ${button('Report a problem', 'categories')}
      ${button('Back to order', 'order', true)}
    `;
  } else if (state.page === 'categories') {
    content = `
      <button type="button" class="back" data-action="order">← Order</button>
      <h1 id="page-title" tabindex="-1">What went wrong?</h1>
      <p>Choose a problem type.</p>
      ${categories.map((category, index) => `
        <button type="button" class="role-card" data-category="${index}">
          <span><strong>${escapeHtml(category)}</strong></span>
          <span class="arrow" aria-hidden="true">→</span>
        </button>
      `).join('')}
    `;
  } else if (state.page === 'report') {
    content = reportForm();
  } else if (state.page === 'saved' && state.savedReport) {
    const report = state.savedReport;
    content = `
      <div class="status" aria-hidden="true">✓</div>
      <h1 id="page-title" tabindex="-1">Demo report saved</h1>
      <p>Nothing has been sent to the restaurant.</p>
      <article class="order">
        <h2>${escapeHtml(report.category)}</h2>
        <p style="white-space: pre-wrap">${escapeHtml(report.description)}</p>
        ${report.photoUrl ? `
          <img class="photo" src="${escapeHtml(report.photoUrl)}" alt="Photo saved with demo report">
        ` : ''}
      </article>
      ${button('Back to order', 'order')}
    `;
  }

  app.innerHTML = `
    <header class="top">
      <div class="brand">NOVA<span> ✳</span></div>
      <span class="role-switch">Customer</span>
    </header>
    ${content}
  `;

  if (focusHeading) {
    document.querySelector('#page-title')?.focus();
    window.scrollTo(0, 0);
  }
}

function navigate(page) {
  state.page = page;
  state.error = '';
  render(true);
}

app.addEventListener('click', event => {
  const categoryButton = event.target.closest('[data-category]');

  if (categoryButton) {
    state.category = categories[Number(categoryButton.dataset.category)];
    navigate('report');
    return;
  }

  const actionButton = event.target.closest('[data-action]');
  if (!actionButton) return;

  const action = actionButton.dataset.action;

  if (action === 'confirm-receipt') {
    navigate('confirm');
  } else if (action === 'receive') {
    // Future integration: await the receipt endpoint before showing success.
    state.received = true;
    navigate('received');
  } else if (action === 'remove-photo') {
    if (state.photoUrl && state.photoUrl !== state.savedReport?.photoUrl) {
      URL.revokeObjectURL(state.photoUrl);
    }
    state.photoUrl = null;
    state.photoName = '';
    render();
  } else {
    navigate(action);
  }
});

app.addEventListener('input', event => {
  if (event.target.id === 'description') {
    state.description = event.target.value;
  }
});

app.addEventListener('change', event => {
  if (event.target.id !== 'photo') return;

  const file = event.target.files[0];
  if (!file) return;

  if (!file.type.startsWith('image/') || file.size > 10 * 1024 * 1024) {
    state.error = 'Choose an image smaller than 10 MB.';
    render();
    return;
  }

  if (state.photoUrl && state.photoUrl !== state.savedReport?.photoUrl) {
    URL.revokeObjectURL(state.photoUrl);
  }
  state.photoUrl = URL.createObjectURL(file);
  state.photoName = file.name;
  state.error = '';
  render();
});

app.addEventListener('submit', event => {
  if (event.target.id !== 'report-form') return;
  event.preventDefault();

  if (!state.description.trim()) {
    state.error = 'Please describe the problem.';
    render();
    document.querySelector('#description').focus();
    return;
  }

  // Future integration: upload using FormData and wait for backend success.
  const previousPhoto = state.savedReport?.photoUrl;
  state.savedReport = {
    category: state.category,
    description: state.description.trim(),
    photoUrl: state.photoUrl
  };
  if (previousPhoto && previousPhoto !== state.photoUrl) {
    URL.revokeObjectURL(previousPhoto);
  }
  navigate('saved');
});

render();
