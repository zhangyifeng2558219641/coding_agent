package com.example.mall.controller;

import com.example.mall.dto.AddCartRequest;
import com.example.mall.dto.CartItemView;
import com.example.mall.dto.UpdateCartRequest;
import com.example.mall.service.CartService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 购物车控制器(需登录,按用户隔离):
 * GET    /api/cart          购物车列表
 * POST   /api/cart          加购
 * PUT    /api/cart/{id}     修改数量
 * DELETE /api/cart/{id}     删除单项
 * DELETE /api/cart          清空
 */
@RestController
@RequestMapping("/api/cart")
public class CartController {

    private final CartService cartService;

    @Autowired
    public CartController(CartService cartService) {
        this.cartService = cartService;
    }

    @GetMapping
    public List<CartItemView> list(@RequestAttribute("userId") Long userId) {
        return cartService.list(userId);
    }

    @PostMapping
    public CartItemView add(@RequestAttribute("userId") Long userId,
                            @Valid @RequestBody AddCartRequest req) {
        return cartService.add(userId, req.getProductId(), req.getQuantity());
    }

    @PutMapping("/{id}")
    public CartItemView update(@RequestAttribute("userId") Long userId,
                               @PathVariable Long id,
                               @Valid @RequestBody UpdateCartRequest req) {
        return cartService.updateQuantity(userId, id, req.getQuantity());
    }

    @DeleteMapping("/{id}")
    public Map<String, Object> remove(@RequestAttribute("userId") Long userId, @PathVariable Long id) {
        cartService.remove(userId, id);
        return Map.of("message", "已删除");
    }

    @DeleteMapping
    public Map<String, Object> clear(@RequestAttribute("userId") Long userId) {
        cartService.clear(userId);
        return Map.of("message", "已清空");
    }
}
