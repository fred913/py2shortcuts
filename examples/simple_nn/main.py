import tensors

predicted_class = tensors.argmax(
    [
        tensors.dot([1.0, 2.0, 0.5], [0.8, -0.3, 0.5]) + 0.2,
        tensors.dot([1.0, 2.0, 0.5], [-0.6, 0.9, 0.1]) - 0.1,
    ]
)

print(f"predicted_class={predicted_class}")
