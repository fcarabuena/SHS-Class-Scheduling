// Shows a notification when a followed section's timetable changes, and opens it on tap.
self.addEventListener("push", (event) => {
  const message = event.data ? event.data.json() : {};
  event.waitUntil(
    self.registration.showNotification(message.title || "Timetable changed", {
      body: message.body || "",
      tag: message.url, // one notification per timetable, replaced by newer ones
      data: { url: message.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.openWindow(event.notification.data.url));
});
