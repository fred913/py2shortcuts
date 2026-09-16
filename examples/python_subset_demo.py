from py2shortcuts import shortcuts


def square(x):
    return x * x


name = input("Your name?")
limit = 4
values = ["alpha", "beta", "gamma"]
meta = {"project": "py2shortcuts", "count": len(values)}

print(f"Hello {name}; project={meta['project']}")

for i in range(1, limit):
    value = square(i)
    if value >= 4:
        shortcuts.notification(f"square({i}) = {value}", title="py2shortcuts")
    else:
        print(f"small: {value}")

for item in values:
    print(item, end="")
