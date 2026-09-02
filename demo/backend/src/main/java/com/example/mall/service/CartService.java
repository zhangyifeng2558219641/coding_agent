package com.example.mall.service;

import com.example.mall.dto.CartItemView;
import com.example.mall.entity.CartItem;
import com.example.mall.entity.Product;
import com.example.mall.repository.CartRepository;
import com.example.mall.repository.ProductRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 购物车服务:加购/列表/改数量/删除/清空,按用户隔离。
 * 规则:仅上架商品可加购;加购与改数量均不得超过库存;同一用户同一商品累加数量。
 */
@Service
public class CartService {

    private final CartRepository cartRepository;
    private final ProductRepository productRepository;

    @Autowired
    public CartService(CartRepository cartRepository, ProductRepository productRepository) {
        this.cartRepository = cartRepository;
        this.productRepository = productRepository;
    }

    public List<CartItemView> list(Long userId) {
        return cartRepository.listByUser(userId);
    }

    /** 加购:商品存在且上架,数量在库存范围内,已存在则累加 */
    public CartItemView add(Long userId, Long productId, int quantity) {
        if (quantity <= 0) {
            throw new IllegalArgumentException("数量必须大于0");
        }
        Product product = productRepository.findById(productId);
        if (product == null) {
            throw new IllegalArgumentException("商品不存在");
        }
        if (!"ON_SALE".equals(product.getStatus())) {
            throw new IllegalArgumentException("商品已下架,无法加入购物车");
        }
        if (quantity > product.getStock()) {
            throw new IllegalArgumentException("库存不足,当前库存 " + product.getStock());
        }

        CartItem exist = cartRepository.findByUserAndProduct(userId, productId);
        if (exist != null) {
            int newQuantity = exist.getQuantity() + quantity;
            if (newQuantity > product.getStock()) {
                throw new IllegalArgumentException("库存不足,当前购物车已有 " + exist.getQuantity() + " 件");
            }
            cartRepository.updateQuantity(exist.getId(), newQuantity);
        } else {
            cartRepository.insert(userId, productId, quantity);
        }
        return cartRepository.listByUser(userId).stream()
                .filter(v -> v.getProductId().equals(productId))
                .findFirst()
                .orElse(null);
    }

    /** 修改数量:校验归属与库存 */
    public CartItemView updateQuantity(Long userId, Long cartItemId, int quantity) {
        if (quantity <= 0) {
            throw new IllegalArgumentException("数量必须大于0");
        }
        CartItem item = cartRepository.findByIdAndUser(cartItemId, userId);
        if (item == null) {
            throw new IllegalArgumentException("购物车项不存在");
        }
        Product product = productRepository.findById(item.getProductId());
        if (product != null && quantity > product.getStock()) {
            throw new IllegalArgumentException("库存不足,当前库存 " + product.getStock());
        }
        cartRepository.updateQuantity(cartItemId, quantity);
        return cartRepository.listByUser(userId).stream()
                .filter(v -> v.getCartItemId().equals(cartItemId))
                .findFirst()
                .orElse(null);
    }

    public void remove(Long userId, Long cartItemId) {
        CartItem item = cartRepository.findByIdAndUser(cartItemId, userId);
        if (item == null) {
            throw new IllegalArgumentException("购物车项不存在");
        }
        cartRepository.delete(cartItemId);
    }

    public void clear(Long userId) {
        cartRepository.deleteByUser(userId);
    }
}
