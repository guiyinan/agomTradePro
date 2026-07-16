export function debounce(callback, waitMs = 120) {
    let timer = null;
    return function debounced(...args) {
        if (timer !== null) {
            clearTimeout(timer);
        }
        timer = setTimeout(() => {
            timer = null;
            callback.apply(this, args);
        }, waitMs);
    };
}
