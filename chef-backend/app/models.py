from app import db


ingredients = db.Table(
    'ingredients',
    db.Column("recipe_id", db.Integer, db.ForeignKey("recipe.id"), primary_key=True),
    db.Column("ingredient_item_id", db.Integer, db.ForeignKey("ingredient_item.id"), primary_key=True)
)

tags = db.Table(
    'tags',
    db.Column("recipe_id", db.Integer, db.ForeignKey("recipe.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tag.id"), primary_key=True)
)

category_tags = db.Table(
    'category_tags',
    db.Column("category_id", db.Integer, db.ForeignKey("category.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tag.id"), primary_key=True)
)


def _dictify(obj, depth=100):
    if obj is None:
        return None
    if issubclass(obj.__class__, Base) and depth > 0:
        return obj.get_dictionary(depth=depth-1)
    if issubclass(obj.__class__, list):
        if depth > 1:
            return [_dictify(o, depth=depth - 1) for o in obj]
        else:
            return [str(o) for o in obj]
    try:
        return float(obj)
    except (TypeError, ValueError, SyntaxError):
        pass
    return str(obj)


class Base(db.Model):
    __abstract__ = True
    __items__ = ["id"]

    id = db.Column(db.Integer, primary_key=True)

    def _get_attributes(self, exclude=None) -> dict:
        """Get 'public' attributes to be parsed into JSON response"""
        if not exclude:
            exclude = []

        result = {}
        for attr in self.__items__:
            try:
                if attr in exclude:
                    continue
                result[attr] = self.__getattribute__(attr)
            except AttributeError:
                continue
        return result

    def get_dictionary(self, depth=99, exclude=None):
        """Serialize recursively according to the __items__ attribute."""
        return {
            k: _dictify(v, depth=depth) for k, v in self._get_attributes(exclude=exclude).items()
        }

    @property
    def dictionary(self):
        """Serialize recursively according to the __items__ attribute."""
        return self.get_dictionary()

    def _repr(self, **kwargs):
        """Create repr string."""
        kw = {f"{str(k)}={v}" for k, v in kwargs.items()}
        return f'<{self.__class__.__name__} ({", ".join(kw)})>'

    def __repr__(self):
        """Default for all subclasses: everything 'public'."""
        return self._repr(**self.get_dictionary())


class Unit(Base):
    __items__ = ["name", "grams"]
    name = db.Column(db.String(80), nullable=False, unique=True)
    grams = db.Column(db.Float, default=0)


class Tag(Base):
    __items__ = ["name"]
    name = db.Column(db.String(80), nullable=False)


class Ingredient(Base):
    __items__ = ["id", "name", "energy", "fats",
                 "carbs", "proteins", "fibres", "salt", "is_liquid", "density"]

    name = db.Column(db.String(80), nullable=False)
    approx_per_piece = db.Column(db.Float, default=0)  # g / piece

    energy = db.Column(db.Float, default=0)  # kcal
    fats = db.Column(db.Float, default=0)  # g / 100g
    carbs = db.Column(db.Float, default=0)  # g / 100g
    proteins = db.Column(db.Float, default=0)  # g / 100g
    fibres = db.Column(db.Float, default=0)  # g / 100g
    salt = db.Column(db.Float, default=0)  # g / 100g

    is_liquid = db.Column(db.Boolean, default=False)
    density = db.Column(db.Float, default=1000)  # g / L

    def __repr__(self) -> str:
        return self._repr(id=self.id, name=self.name)


class IngredientItem(Base):
    """
    -> [included in shopping list] <amount> <unit> <ingredient> (<note>)
    -> [x] 400 g tomatoes (roughly chopped)
    """
    __items__ = ["ingredient", "amount", "unit", "note"]

    ingredient_id = db.Column(db.Integer, db.ForeignKey(Ingredient.id))
    ingredient = db.relationship(Ingredient, uselist=False)
    amount = db.Column(db.Float, default=0)
    unit_id = db.Column(db.Integer, db.ForeignKey('unit.id'))
    unit = db.relationship("Unit")

    note = db.Column(db.String(10), nullable=True)
    exclude = db.Column(db.Boolean(), default=False)  # todo: remove?

    def __repr__(self):
        return self._repr(ingredient=self.ingredient.name, amount=self.amount, unit=self.unit)


class Category(Base):
    __items__ = ["id", "name", "tags"]
    name = db.Column(db.String(80), nullable=False)
    tags = db.relationship(Tag, secondary=category_tags, lazy="subquery",
                           backref=db.backref("categories, lazy=True"))


class Recipe(Base):
    __items__ = ["id", "title", "subtitle", "ingredients", "body",
                 "source", "source_name", "tags", "portions"]

    title = db.Column(db.String(80), nullable=False)
    subtitle = db.Column(db.String(50), nullable=True)
    source_name = db.Column(db.String(100), nullable=True)
    source = db.Column(db.String(100), nullable=True)
    draft = db.Column(db.Boolean(), default=False)
    portions = db.Column(db.Integer, default=4)
    ingredients = db.relationship(IngredientItem, secondary=ingredients, lazy="subquery",
                                  backref=db.backref("recipes", lazy=False), cascade="all")
    tags = db.relationship(Tag, secondary=tags, lazy="subquery",
                           backref=db.backref("recipes, lazy=False"))

    # HTML content + rich text editor on the frontend
    body = db.Column(db.String(1000), nullable=True)
