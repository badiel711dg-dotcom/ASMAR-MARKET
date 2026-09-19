self.addEventListener("push", function (event) {
    let data = {};

    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = {
            title: "ASMAR MARKET",
            body: event.data ? event.data.text() : "لديك إشعار جديد"
        };
    }

    const title = data.title || "ASMAR MARKET";

    const options = {
        body: data.body || "لديك إشعار جديد",
        icon: data.icon || "/static/favicon.ico",
        badge: data.badge || "/static/favicon.ico",
        data: {
            url: data.url || "/"
        }
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

self.addEventListener("notificationclick", function (event) {
    event.notification.close();

    const url = event.notification.data?.url || "/";

    event.waitUntil(
        clients.matchAll({
            type: "window",
            includeUncontrolled: true
        }).then(function (clientList) {
            for (const client of clientList) {
                if ("focus" in client) {
                    client.navigate(url);
                    return client.focus();
                }
            }

            if (clients.openWindow) {
                return clients.openWindow(url);
            }
        })
    );
});
