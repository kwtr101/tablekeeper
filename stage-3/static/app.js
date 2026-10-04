(() => {
  const $ = (selector) => document.querySelector(selector);
  const apiKeyInput = $('#apiKey');
  const restaurantSelect = $('#restaurantSelect');
  const tableRestaurant = $('#tableRestaurant');
  const restaurantList = $('#restaurantList');
  const reservationsList = $('#reservationsList');
  const availabilityResult = $('#availabilityResult');
  const foldChoiceWrap = $('#foldChoiceWrap');
  const foldChoice = $('#foldChoice');
  const toast = $('#toast');
  const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const timeZoneFormatterCache = new Map();
  let restaurants = [];
  let toastTimer;

  $('#timezoneLabel').textContent = browserTimezone;
  $('#restaurantTimezone').value = browserTimezone;
  apiKeyInput.value = sessionStorage.getItem('tablekeeperApiKey') || '';

  function notify(message, isError = false) {
    toast.textContent = message;
    toast.classList.toggle('error', isError);
    toast.classList.add('show');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove('show'), 3600);
  }

  function setConnection(connected, label) {
    $('#connectionDot').classList.toggle('connected', connected);
    $('#connectionLabel').textContent = label || (connected ? 'Connected' : 'Not connected');
  }

  function errorMessage(payload, fallback) {
    if (typeof payload?.detail === 'string') return payload.detail;
    if (Array.isArray(payload?.detail)) return payload.detail.map((item) => item.msg).join('; ');
    return fallback;
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const key = sessionStorage.getItem('tablekeeperApiKey') || apiKeyInput.value.trim();
    if (key) headers.set('Authorization', `Bearer ${key}`);
    if (options.body !== undefined) headers.set('Content-Type', 'application/json');
    const response = await fetch(path, { ...options, headers });
    if (response.status === 204) return null;
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json() : null;
    if (response.status === 401) {
      throw new Error('Authentication failed. Enter this Tablekeeper instance\'s BOOTSTRAP_ADMIN_TOKEN or a Tablekeeper API key.');
    }
    if (!response.ok) throw new Error(errorMessage(payload, `Request failed (${response.status})`));
    return payload;
  }

  function option(value, label) {
    const element = document.createElement('option');
    element.value = String(value);
    element.textContent = label;
    return element;
  }

  function showEmpty(container, message) {
    const element = document.createElement('div');
    element.className = 'empty-state';
    element.textContent = message;
    container.replaceChildren(element);
  }

  function setRestaurants(items) {
    restaurants = items;
    const selected = restaurantSelect.value;
    restaurantSelect.replaceChildren(option('', 'Choose a restaurant'));
    tableRestaurant.replaceChildren(option('', 'Select restaurant'));
    for (const restaurant of items) {
      const label = `${restaurant.name} · ${restaurant.timezone}`;
      restaurantSelect.append(option(restaurant.id, label));
      tableRestaurant.append(option(restaurant.id, label));
    }
    if (items.some((restaurant) => String(restaurant.id) === selected)) restaurantSelect.value = selected;
    syncRestaurantTimezone();
  }

  function syncRestaurantTimezone() {
    const restaurant = restaurants.find((item) => String(item.id) === restaurantSelect.value);
    $('#timezoneLabel').textContent = restaurant?.timezone || browserTimezone;
  }

  function renderRestaurants(items, tablesByRestaurant) {
    if (!items.length) {
      showEmpty(restaurantList, 'No restaurants yet. An administrator can add the first venue below.');
      return;
    }
    const cards = items.map((restaurant) => {
      const card = document.createElement('article');
      card.className = 'restaurant-card';
      const name = document.createElement('span');
      name.className = 'restaurant-name';
      name.textContent = restaurant.name;
      const zone = document.createElement('span');
      zone.className = 'restaurant-zone';
      zone.textContent = restaurant.timezone;
      const count = document.createElement('span');
      count.className = 'restaurant-table-count';
      const tables = tablesByRestaurant.get(String(restaurant.id)) ?? [];
      const tableSummary = tables.map((table) => `${table.name} (${table.capacity})`).join(', ');
      count.textContent = `${tables.length} active table${tables.length === 1 ? '' : 's'}`;
      const tableDetails = document.createElement('span');
      tableDetails.className = 'restaurant-tables';
      tableDetails.textContent = tableSummary || 'No active tables';
      card.append(name, zone, count, tableDetails);
      return card;
    });
    restaurantList.replaceChildren(...cards);
  }

  function renderReservations(items) {
    $('#reservationCount').textContent = String(items.length);
    if (!items.length) {
      showEmpty(reservationsList, 'No reservations found for this key. New bookings will appear here.');
      return;
    }
    const rows = items.map((reservation) => {
      const row = document.createElement('article');
      row.className = 'reservation-row';
      const main = document.createElement('div');
      main.className = 'reservation-main';
      const title = document.createElement('div');
      title.className = 'reservation-title';
      title.textContent = `Reservation #${reservation.id} · ${reservation.party_size} guest${reservation.party_size === 1 ? '' : 's'}`;
      const subtitle = document.createElement('div');
      subtitle.className = 'reservation-subtitle';
      const timezone = restaurants.find((item) => String(item.id) === String(reservation.restaurant_id))?.timezone;
      const starts = new Date(reservation.starts_at).toLocaleString([], {
        dateStyle: 'medium', timeStyle: 'short', ...(timezone ? { timeZone: timezone } : {})
      });
      const ends = new Date(reservation.ends_at).toLocaleTimeString([], {
        hour: 'numeric', minute: '2-digit', ...(timezone ? { timeZone: timezone } : {})
      });
      subtitle.textContent = `${starts} – ${ends} · Table ${reservation.table_id} · Venue ${reservation.restaurant_id}`;
      main.append(title, subtitle);
      const status = document.createElement('span');
      const isConfirmed = reservation.status === 'confirmed';
      status.className = `status-pill${isConfirmed ? '' : ' cancelled'}`;
      status.textContent = reservation.status || 'confirmed';
      row.append(main, status);
      if (isConfirmed) {
        const cancel = document.createElement('button');
        cancel.className = 'cancel-button';
        cancel.type = 'button';
        cancel.dataset.reservationId = reservation.id;
        cancel.textContent = 'Cancel';
        row.append(cancel);
      }
      return row;
    });
    reservationsList.replaceChildren(...rows);
  }

  async function loadWorkspace() {
    const [venues, reservations] = await Promise.all([api('/restaurants'), api('/reservations')]);
    const tableResults = await Promise.all(venues.map(async (restaurant) => {
      const tables = await api(`/restaurants/${encodeURIComponent(restaurant.id)}/tables`);
      return [String(restaurant.id), tables];
    }));
    const tablesByRestaurant = new Map(tableResults);
    setRestaurants(venues);
    renderRestaurants(venues, tablesByRestaurant);
    renderReservations(reservations);
    $('#restaurantCount').textContent = String(venues.length);
    $('#tableCount').textContent = String(tableResults.reduce((sum, [, tables]) => sum + tables.length, 0));
    $('#statsFootnote').textContent = 'Live counts for the API key in this session.';
    setConnection(true, 'Connected');
  }

  async function withBusy(button, callback) {
    const original = button.textContent;
    button.disabled = true;
    try {
      await callback();
    } catch (error) {
      notify(error.message || 'Something went wrong.', true);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  function timezoneFormatter(timezone) {
    if (!timeZoneFormatterCache.has(timezone)) {
      timeZoneFormatterCache.set(timezone, new Intl.DateTimeFormat('en-GB', {
        timeZone: timezone,
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hourCycle: 'h23'
      }));
    }
    return timeZoneFormatterCache.get(timezone);
  }

  function zoneParts(instant, timezone) {
    const parts = Object.fromEntries(timezoneFormatter(timezone).formatToParts(instant).map((part) => [part.type, part.value]));
    return {
      year: Number(parts.year), month: Number(parts.month), day: Number(parts.day),
      hour: Number(parts.hour), minute: Number(parts.minute), second: Number(parts.second)
    };
  }

  function offsetAt(instant, timezone) {
    const parts = zoneParts(instant, timezone);
    const representedAsUtc = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
    return Math.round((representedAsUtc - instant.getTime()) / 60000);
  }

  function offsetText(minutes) {
    const sign = minutes >= 0 ? '+' : '-';
    const absolute = Math.abs(minutes);
    return `${sign}${String(Math.floor(absolute / 60)).padStart(2, '0')}:${String(absolute % 60).padStart(2, '0')}`;
  }

  function startCandidates(localValue, timezone) {
    const match = localValue.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
    if (!match) throw new Error('Choose a valid date and time.');
    const [, yearText, monthText, dayText, hourText, minuteText] = match;
    const wall = {
      year: Number(yearText), month: Number(monthText), day: Number(dayText),
      hour: Number(hourText), minute: Number(minuteText), second: 0
    };
    const wallAsUtc = Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute, 0);
    const offsets = new Set([-36, -12, 0, 12, 36].map((hours) => offsetAt(new Date(wallAsUtc + hours * 3600000), timezone)));
    const candidates = [];
    for (const offset of offsets) {
      const instant = new Date(wallAsUtc - offset * 60000);
      const actual = zoneParts(instant, timezone);
      if (actual.year === wall.year && actual.month === wall.month && actual.day === wall.day && actual.hour === wall.hour && actual.minute === wall.minute) {
        candidates.push({ instant, offset });
      }
    }
    if (!candidates.length) throw new Error('That local time does not exist in this restaurant’s timezone because of a daylight-saving change.');
    candidates.sort((left, right) => left.instant - right.instant);
    return candidates;
  }

  function formatOccurrence(candidate) {
    const time = new Intl.DateTimeFormat([], {
      timeZone: restaurants.find((item) => String(item.id) === restaurantSelect.value)?.timezone,
      hour: 'numeric', minute: '2-digit', timeZoneName: 'short'
    }).format(candidate.instant);
    return `${time} (UTC${offsetText(candidate.offset)})`;
  }

  function syncFoldChoice() {
    const restaurant = restaurants.find((item) => String(item.id) === restaurantSelect.value);
    if (!restaurant || !$('#startsAt').value) {
      foldChoiceWrap.hidden = true;
      return;
    }
    try {
      const candidates = startCandidates($('#startsAt').value, restaurant.timezone);
      if (candidates.length < 2) {
        foldChoiceWrap.hidden = true;
        return;
      }
      foldChoice.replaceChildren(...candidates.map((candidate, index) => option(
        index,
        `${index === 0 ? 'First' : 'Second'} occurrence — ${formatOccurrence(candidate)}`
      )));
      foldChoice.value = '0';
      foldChoiceWrap.hidden = false;
    } catch {
      foldChoiceWrap.hidden = true;
    }
  }

  function offsetAwareStart(localValue, timezone) {
    const candidates = startCandidates(localValue, timezone);
    const selected = candidates[foldChoiceWrap.hidden ? 0 : Number(foldChoice.value)] ?? candidates[0];
    return `${localValue}:00${offsetText(selected.offset)}`;
  }

  function bookingPayload() {
    const restaurant = restaurants.find((item) => String(item.id) === restaurantSelect.value);
    if (!restaurant) throw new Error('Choose a restaurant first.');
    const start = $('#startsAt').value;
    if (!start) throw new Error('Choose a reservation date and time.');
    return {
      restaurant_id: Number(restaurant.id),
      party_size: Number($('#partySize').value),
      starts_at: offsetAwareStart(start, restaurant.timezone),
      timezone: restaurant.timezone,
      duration_minutes: Number($('#duration').value)
    };
  }

  $('#connectForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const key = apiKeyInput.value.trim();
    if (!key) return;
    sessionStorage.setItem('tablekeeperApiKey', key);
    try {
      await loadWorkspace();
      notify('Workspace connected.');
    } catch (error) {
      sessionStorage.removeItem('tablekeeperApiKey');
      setConnection(false, 'Connection failed');
      notify(error.message || 'Could not connect to the API.', true);
    }
  });

  $('#refreshButton').addEventListener('click', () => withBusy($('#refreshButton'), async () => {
    await loadWorkspace();
    notify('Dashboard refreshed.');
  }));
  $('#loadReservationsButton').addEventListener('click', () => withBusy($('#loadReservationsButton'), async () => {
    renderReservations(await api('/reservations'));
    notify('Reservation list refreshed.');
  }));
  $('#revealKey').addEventListener('click', () => {
    const reveal = apiKeyInput.type === 'password';
    apiKeyInput.type = reveal ? 'text' : 'password';
    $('#revealKey').setAttribute('aria-label', reveal ? 'Hide API key' : 'Show API key');
  });
  restaurantSelect.addEventListener('change', () => {
    syncRestaurantTimezone();
    syncFoldChoice();
  });
  $('#startsAt').addEventListener('input', syncFoldChoice);

  $('#availabilityButton').addEventListener('click', () => withBusy($('#availabilityButton'), async () => {
    const result = await api('/availability', { method: 'POST', body: JSON.stringify(bookingPayload()) });
    availabilityResult.textContent = result.available ? 'A suitable table is available for this time.' : 'No table is available for this time.';
    availabilityResult.className = `availability-result ${result.available ? 'available' : 'unavailable'}`;
  }));

  $('#bookingForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const submitButton = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
    await withBusy(submitButton, async () => {
      const reservation = await api('/reservations', { method: 'POST', body: JSON.stringify(bookingPayload()) });
      availabilityResult.textContent = `Reservation #${reservation.id} confirmed.`;
      availabilityResult.className = 'availability-result available';
      notify(`Table ${reservation.table_id} reserved.`);
      const reservations = await api('/reservations');
      renderReservations(reservations);
    });
  });

  reservationsList.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-reservation-id]');
    if (!button) return;
    const reservationId = button.dataset.reservationId;
    if (!window.confirm(`Cancel reservation #${reservationId}?`)) return;
    await withBusy(button, async () => {
      await api(`/reservations/${encodeURIComponent(reservationId)}`, { method: 'DELETE' });
      renderReservations(await api('/reservations'));
      notify(`Reservation #${reservationId} cancelled.`);
    });
  });

  $('#restaurantForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const submitButton = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
    await withBusy(submitButton, async () => {
      await api('/admin/restaurants', {
        method: 'POST',
        body: JSON.stringify({ name: $('#restaurantName').value.trim(), timezone: $('#restaurantTimezone').value.trim() })
      });
      event.currentTarget.reset();
      $('#restaurantTimezone').value = browserTimezone;
      await loadWorkspace();
      notify('Restaurant added.');
    });
  });

  $('#tableForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const submitButton = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
    await withBusy(submitButton, async () => {
      const restaurantId = $('#tableRestaurant').value;
      await api(`/admin/restaurants/${encodeURIComponent(restaurantId)}/tables`, {
        method: 'POST',
        body: JSON.stringify({ name: $('#tableName').value.trim(), capacity: Number($('#tableCapacity').value) })
      });
      event.currentTarget.reset();
      $('#tableCapacity').value = '4';
      await loadWorkspace();
      notify('Table added.');
    });
  });

  $('#createKeyButton').addEventListener('click', () => withBusy($('#createKeyButton'), async () => {
    const result = await api('/admin/api-keys', { method: 'POST', body: JSON.stringify({ role: 'customer' }) });
    const notice = $('#newKeyNotice');
    notice.replaceChildren();
    const title = document.createElement('strong');
    title.textContent = `Customer key #${result.id} · copy now`;
    const token = document.createElement('span');
    token.textContent = result.api_key;
    notice.append(title, token);
    notice.hidden = false;
    notify('Customer key created. It will not be shown again.');
  }));

  $('#revokeKeyButton').addEventListener('click', () => withBusy($('#revokeKeyButton'), async () => {
    const keyId = $('#revokeKeyId').value;
    if (!keyId) throw new Error('Enter a customer key ID.');
    await api(`/admin/api-keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
    $('#revokeKeyId').value = '';
    notify(`Customer key #${keyId} revoked.`);
  }));

  if (apiKeyInput.value) {
    loadWorkspace().catch((error) => {
      sessionStorage.removeItem('tablekeeperApiKey');
      apiKeyInput.value = '';
      setConnection(false, 'Not connected');
      notify(error.message || 'Saved session key is no longer valid.', true);
    });
  }
})();
