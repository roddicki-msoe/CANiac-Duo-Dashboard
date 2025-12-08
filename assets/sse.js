// Ensure namespace exists
if (!window.dash_clientside) window.dash_clientside = {};

let eventSource = new EventSource("/stream");

// Incoming CAN message from Flask SSE
eventSource.onmessage = function (event) {
    let msg = JSON.parse(event.data);

    // Push into Dash via Store
    let store = document.querySelector('[data-dash-react-root] #can-store');

    if (store) {
        // Set the store's data property using a CustomEvent
        const e = new CustomEvent("input", { detail: msg });
        store.dispatchEvent(e);
    }
};

// Dash clientside namespace (not required but safe)
window.dash_clientside.sse = {};
