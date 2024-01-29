import typing
from typing import List, Generic, TypeVar, Union, Type

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from chef.models import Category as CategoryDb
from chef.schemas import Recipe, Tag, Category, Ingredient, CreateOrUpdateRecipe, \
    IngredientItem, Unit, UpdateIngredient, CreateOrUpdateCategory


C = TypeVar('C', bound=BaseModel)
R = TypeVar('R', bound=BaseModel)
U = TypeVar('U', bound=BaseModel)


class Controller(Generic[C, R, U]):

    @property
    def create_schema(self) -> Type[C]:
        return typing.get_args(self.__orig_bases__[0])[0]

    @property
    def read_schema(self) -> Type[R]:
        return typing.get_args(self.__orig_bases__[0])[1]

    @property
    def update_schema(self) -> Type[U]:
        return typing.get_args(self.__orig_bases__[0])[2]

    async def _fill_model(self,  session: Session, model, data: Union[C, U]):
        """Override for more complex models."""
        for attr, value in data.dict(exclude_none=True).items():
            setattr(model, attr, value)

    async def get_all(self, session: Session) -> List[R]:
        return [
            self.read_schema(**item.dictionary)
            for item in session.scalars(select(self.read_schema.Meta.orm_model)).all()
        ]

    async def get_single(self, session: Session, item_id: int) -> R:
        db_item = session.get(self.read_schema.Meta.orm_model, item_id)
        if not db_item:
            raise HTTPException(
                status_code=404, detail=f"{self.read_schema.__class__} id={item_id} not found"
            )
        return self.read_schema(**db_item.dictionary)

    async def delete_single(self, session: Session, item_id: int) -> None:
        item = session.get(self.read_schema.Meta.orm_model, item_id)
        if not item:
            raise HTTPException(
                status_code=404, detail=f"{self.read_schema.__class__} id={item_id} not found"
            )
        session.delete(item)
        session.commit()

    async def create(self, session: Session, data: C) -> R:
        new_model = self.read_schema.Meta.orm_model()
        await self._fill_model(session, new_model, data)
        session.add(new_model)
        session.commit()
        return await self.get_single(session, item_id=new_model.id)

    async def create_or_update(self, session: Session, data: Union[U, C]) -> R:
        if getattr(data, "id", None):
            item = session.get(self.read_schema.Meta.orm_model, data.id)
        else:
            item = self.read_schema.Meta.orm_model()
        await self._fill_model(session, item, data)
        session.add(item)
        session.commit()
        return self.read_schema(**session.get(self.read_schema.Meta.orm_model, item.id).dictionary)

    async def update(self, session: Session, item_id: int, data: U) -> R:
        item = session.get(self.read_schema.Meta.orm_model, item_id)
        if not item:
            raise HTTPException(
                status_code=404, detail=f"{self.read_schema.__class__} id={data.id} not found"
            )
        await self._fill_model(session, item, data)
        session.add(item)
        session.commit()
        return await self.get_single(session, item.id)


class TagController(Controller[Tag, Tag, Tag]):
    ...


class IngredientsController(Controller[UpdateIngredient, Ingredient, UpdateIngredient]):

    async def delete_single(self, session: Session, item_id: int) -> None:
        ingredient = session.get(self.read_schema.Meta.orm_model, item_id)
        if ingredient.ingredients_items:
            recipes = [
                r.title
                for item in ingredient.ingredients_items
                for r in item.recipes
            ]
            if recipes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Ingredient still attached to some recipes: {', '.join(recipes)}",
                )
        return await super().delete_single(session, item_id)


class CategoriesController(Controller[CreateOrUpdateCategory, Category, CreateOrUpdateCategory]):

    async def _fill_model(self,  session: Session, model: CategoryDb, data: CreateOrUpdateCategory):
        tags = []
        for tag in data.tags:
            item = session.get(Tag.Meta.orm_model, tag.id)
            if not item:
                raise HTTPException(
                    status_code=400, detail=f"Tag id={tag.id} not found"
                )
            tags.append(item)
        for attr, value in data.dict(exclude_none=True, exclude={"tags": True}).items():
            setattr(model, attr, value)
        model.tags = tags


class UnitsController(Controller[Unit, Unit, Unit]):

    async def create_or_update(self, session: Session, data: Union[U, C]) -> R:
        if getattr(data, "id", None):
            item = session.get(self.read_schema.Meta.orm_model, data.id)
        else:
            same_name = session \
                .query(self.read_schema.Meta.orm_model) \
                .filter_by(name=data.name) \
                .first()
            if same_name:
                item = same_name
            else:
                item = self.read_schema.Meta.orm_model()
        for attr in data.dict(exclude={"id": True}):
            setattr(item, attr, getattr(data, attr))
        session.add(item)
        session.commit()
        return self.read_schema(
            **session.query(self.read_schema.Meta.orm_model)
            .filter_by(name=item.name)
            .first()
            .dictionary
        )


class RecipesController(Controller[CreateOrUpdateRecipe, Recipe, CreateOrUpdateRecipe]):

    @staticmethod
    async def _get_ingredients_and_tags(session: Session, data: CreateOrUpdateRecipe):
        """Load (or create and load) entire models and for specified ingredients and tags."""
        updated_ingredients = []
        ingredients_controller = IngredientsController()
        units_controller = UnitsController()
        for ingredient_item in data.ingredients:
            updated_item = IngredientItem.Meta.orm_model(
                **ingredient_item.dict(exclude={'ingredient': True, 'unit': True})
            )
            u = await units_controller.create_or_update(session, ingredient_item.unit)
            updated_item.unit_id = u.id
            i = await ingredients_controller.create_or_update(session, ingredient_item.ingredient)
            updated_item.ingredient_id = i.id
            updated_ingredients.append(updated_item)

        updated_tags = []
        for tag in data.tags:
            if getattr(tag, "id", None):
                updated_tags.append(session.get(Tag.Meta.orm_model, tag.id))
            else:
                updated_tags.append(
                    Tag.Meta.orm_model(**tag.dict())
                )
        return updated_ingredients, updated_tags

    async def _fill_model(self, session: Session, model, data: Union[C, U]):
        if not model:
            raise HTTPException(
                status_code=404, detail=f"{self.read_schema.__class__} id={data.id} not found"
            )
        for attr, value in data.dict(
                exclude_none=True, exclude={"tags": True, "ingredients": True}
        ).items():
            setattr(model, attr, value)
        updated_ingredients, updated_tags = await self._get_ingredients_and_tags(session, data)
        model.ingredients = updated_ingredients
        model.tags = updated_tags

    async def get_by_category(self, session: Session, category_id: int = None) -> List[Recipe]:
        cat = session.scalars(
            select(Category.Meta.orm_model)
            .filter_by(id=category_id)
            .limit(1)
        ).first()
        if cat:
            result = [recipe for tag in cat.tags for recipe in tag.recipes]
            return [self.read_schema(**r.dictionary) for r in result]
        return []

    async def get_all_and_filter(self, session: Session, **filters: typing.Any) -> List[Recipe]:
        recipes = session.scalars(
            select(self.read_schema.Meta.orm_model)
            .filter_by(**filters)
        ).all()
        return [self.read_schema(**r.dictionary) for r in recipes]

    async def create_or_update(self, session: Session, data: Union[U, C]) -> R:
        raise ValueError("Not allowed on this controller!")
