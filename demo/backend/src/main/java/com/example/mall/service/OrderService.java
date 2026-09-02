package com.example.mall.service;

import com.example.mall.dto.CreateOrderRequest;
import com.example.mall.dto.ReviewRequest;
import com.example.mall.entity.CartItem;
import com.example.mall.entity.Order;
import com.example.mall.entity.OrderItem;
import com.example.mall.entity.Product;
import com.example.mall.entity.Review;
import com.example.mall.entity.User;
import com.example.mall.repository.CartRepository;
import com.example.mall.repository.OrderRepository;
import com.example.mall.repository.PointRecordRepository;
import com.example.mall.repository.ProductRepository;
import com.example.mall.repository.ReviewRepository;
import com.example.mall.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 订单服务:下单(事务:扣库存/生成明细/清购物车)、支付(扣积分/返积分)、取消(恢复库存)、
 * 确认收货、发货(管理端)、评价(更新商品平均分)。
 *
 * 积分规则:
 *   - 抵扣:10 积分 = 1 元(下单时登记,支付时扣减)
 *   - 返利:支付成功后按实付金额每 1 元返 1 积分(向下取整)
 */
@Service
public class OrderService {

    private static final int POINTS_PER_YUAN = 10;

    private final OrderRepository orderRepository;
    private final CartRepository cartRepository;
    private final ProductRepository productRepository;
    private final UserRepository userRepository;
    private final PointRecordRepository pointRecordRepository;
    private final ReviewRepository reviewRepository;

    @Autowired
    public OrderService(OrderRepository orderRepository, CartRepository cartRepository,
                        ProductRepository productRepository, UserRepository userRepository,
                        PointRecordRepository pointRecordRepository, ReviewRepository reviewRepository) {
        this.orderRepository = orderRepository;
        this.cartRepository = cartRepository;
        this.productRepository = productRepository;
        this.userRepository = userRepository;
        this.pointRecordRepository = pointRecordRepository;
        this.reviewRepository = reviewRepository;
    }

    /** 从购物车创建订单(事务:校验库存 -> 生成订单与明细 -> 扣库存加销量 -> 清购物车) */
    @Transactional
    public Order create(Long userId, CreateOrderRequest req) {
        List<CartItem> cartItems = cartRepository.findByIdsAndUser(userId, req.getCartItemIds());
        if (cartItems.isEmpty()) {
            throw new IllegalArgumentException("购物车中没有选中的商品");
        }

        BigDecimal total = BigDecimal.ZERO;
        List<OrderItem> items = new ArrayList<>();
        for (CartItem ci : cartItems) {
            Product p = productRepository.findById(ci.getProductId());
            if (p == null || !"ON_SALE".equals(p.getStatus())) {
                throw new IllegalArgumentException("商品不存在或已下架,请刷新购物车");
            }
            if (p.getStock() < ci.getQuantity()) {
                throw new IllegalArgumentException("库存不足: " + p.getName() + "(当前库存 " + p.getStock() + ")");
            }
            total = total.add(p.getPrice().multiply(BigDecimal.valueOf(ci.getQuantity())));

            OrderItem oi = new OrderItem();
            oi.setProductId(p.getId());
            oi.setProductName(p.getName());
            oi.setPrice(p.getPrice());
            oi.setQuantity(ci.getQuantity());
            items.add(oi);
        }

        // 积分抵扣(10 积分 = 1 元,向下取整,不能超过订单总额)
        User user = userRepository.findById(userId);
        int usePoints = req.getUsePoints() == null ? 0 : Math.max(req.getUsePoints(), 0);
        if (usePoints > user.getPoints()) {
            throw new IllegalArgumentException("积分不足,当前可用 " + user.getPoints());
        }
        BigDecimal discountAmount = BigDecimal.valueOf(usePoints)
                .divide(BigDecimal.valueOf(POINTS_PER_YUAN), 2, RoundingMode.FLOOR);
        if (discountAmount.compareTo(total) > 0) {
            discountAmount = total;
            usePoints = discountAmount.multiply(BigDecimal.valueOf(POINTS_PER_YUAN)).intValue();
        }
        BigDecimal actual = total.subtract(discountAmount);

        Order order = new Order();
        order.setOrderNo(generateOrderNo());
        order.setUserId(userId);
        order.setTotalAmount(total);
        order.setDiscountPoints(usePoints);
        order.setDiscountAmount(discountAmount);
        order.setActualAmount(actual);
        order.setStatus("PENDING_PAYMENT");
        order.setReceiver(req.getReceiver());
        order.setPhone(req.getPhone());
        order.setAddress(req.getAddress());

        Long orderId = orderRepository.insertOrder(order);
        for (OrderItem oi : items) {
            orderRepository.insertOrderItem(orderId, oi);
            int updated = productRepository.deductStockAndAddSales(oi.getProductId(), oi.getQuantity());
            if (updated == 0) {
                throw new IllegalStateException("库存不足: " + oi.getProductName());
            }
        }
        cartRepository.deleteByUserAndIds(userId, req.getCartItemIds());

        Order saved = orderRepository.findOrderById(orderId);
        saved.setItems(orderRepository.findItemsByOrderId(orderId));
        return saved;
    }

    /** 支付(模拟):扣减抵扣积分、按实付返积分,状态置为 PAID */
    @Transactional
    public Order pay(Long userId, Long orderId) {
        Order order = getOwnedOrder(userId, orderId);
        if (!"PENDING_PAYMENT".equals(order.getStatus())) {
            throw new IllegalArgumentException("仅待支付订单可以支付");
        }
        User user = userRepository.findById(userId);

        int balance = user.getPoints();
        int usePoints = order.getDiscountPoints();
        if (usePoints > 0) {
            if (usePoints > balance) {
                throw new IllegalArgumentException("积分不足,当前可用 " + balance);
            }
            balance -= usePoints;
            userRepository.updatePoints(userId, balance);
            pointRecordRepository.insert("SPEND", -usePoints, balance, orderId,
                    "订单支付抵扣 " + order.getOrderNo(), userId);
        }

        int gain = order.getActualAmount().intValue();
        if (gain > 0) {
            balance += gain;
            userRepository.updatePoints(userId, balance);
            pointRecordRepository.insert("GAIN", gain, balance, orderId,
                    "订单消费返积分 " + order.getOrderNo(), userId);
        }

        orderRepository.markPaid(orderId);
        return detail(userId, orderId);
    }

    /** 取消订单(仅待支付):恢复库存、扣减销量 */
    @Transactional
    public Order cancel(Long userId, Long orderId) {
        Order order = getOwnedOrder(userId, orderId);
        if (!"PENDING_PAYMENT".equals(order.getStatus())) {
            throw new IllegalArgumentException("仅待支付订单可以取消");
        }
        for (OrderItem oi : orderRepository.findItemsByOrderId(orderId)) {
            productRepository.restoreStockAndReduceSales(oi.getProductId(), oi.getQuantity());
        }
        orderRepository.markCancelled(orderId);
        return detail(userId, orderId);
    }

    /** 确认收货(仅已发货):状态置为 COMPLETED */
    public Order confirmReceive(Long userId, Long orderId) {
        Order order = getOwnedOrder(userId, orderId);
        if (!"SHIPPED".equals(order.getStatus())) {
            throw new IllegalArgumentException("仅已发货订单可以确认收货");
        }
        orderRepository.markCompleted(orderId);
        return detail(userId, orderId);
    }

    /** 管理端发货(仅已支付) */
    public Order ship(Long orderId) {
        Order order = orderRepository.findOrderById(orderId);
        if (order == null) {
            throw new IllegalArgumentException("订单不存在");
        }
        if (!"PAID".equals(order.getStatus())) {
            throw new IllegalArgumentException("仅已支付订单可以发货");
        }
        orderRepository.markShipped(orderId);
        return detail(order.getUserId(), orderId);
    }

    /** 我的订单列表 */
    public List<Order> listMine(Long userId, String status) {
        return orderRepository.listByUser(userId, status);
    }

    /** 管理端订单列表 */
    public List<Order> listAll(String status, String keyword, String startDate, String endDate) {
        validateDate(startDate, "startDate");
        validateDate(endDate, "endDate");
        return orderRepository.listAll(status, keyword, startDate, endDate);
    }

    private void validateDate(String date, String field) {
        if (date == null || date.isBlank()) {
            return;
        }
        if (!date.trim().matches("\\d{4}-\\d{2}-\\d{2}")) {
            throw new IllegalArgumentException(field + " 日期格式应为 yyyy-MM-dd");
        }
    }

    /** 管理端订单详情(任意用户,含明细与用户昵称/邮箱) */
    public Order adminDetail(Long orderId) {
        Order order = orderRepository.findAdminOrderById(orderId);
        if (order == null) {
            throw new IllegalArgumentException("订单不存在");
        }
        order.setItems(orderRepository.findItemsByOrderId(orderId));
        return order;
    }

    /** 订单详情(校验归属,含明细) */
    public Order detail(Long userId, Long orderId) {
        Order order = getOwnedOrder(userId, orderId);
        order.setItems(orderRepository.findItemsByOrderId(orderId));
        return order;
    }

    /** 评价(仅已完成订单,每个商品明细只能评一次),评价后重算商品平均分 */
    @Transactional
    public Review review(Long userId, Long orderId, ReviewRequest req) {
        Order order = getOwnedOrder(userId, orderId);
        if (!"COMPLETED".equals(order.getStatus())) {
            throw new IllegalArgumentException("仅已完成订单可以评价");
        }
        OrderItem item = orderRepository.findOrderItemById(req.getOrderItemId());
        if (item == null || !item.getOrderId().equals(orderId)) {
            throw new IllegalArgumentException("订单明细不存在");
        }
        if (Boolean.TRUE.equals(item.getReviewed())) {
            throw new IllegalArgumentException("该商品已评价过");
        }

        Review review = new Review();
        review.setUserId(userId);
        review.setOrderId(orderId);
        review.setProductId(item.getProductId());
        review.setRating(req.getRating());
        review.setContent(req.getContent());
        reviewRepository.insert(review);
        orderRepository.markOrderItemReviewed(item.getId());
        updateProductRating(item.getProductId());
        return review;
    }

    private void updateProductRating(Long productId) {
        int count = reviewRepository.countByProduct(productId);
        BigDecimal avg = reviewRepository.avgRatingByProduct(productId);
        if (avg != null) {
            avg = avg.setScale(1, RoundingMode.HALF_UP);
        }
        productRepository.updateAvgRating(productId, avg);
    }

    private Order getOwnedOrder(Long userId, Long orderId) {
        Order order = orderRepository.findOrderById(orderId);
        if (order == null) {
            throw new IllegalArgumentException("订单不存在");
        }
        if (!order.getUserId().equals(userId)) {
            throw new IllegalArgumentException("无权访问该订单");
        }
        return order;
    }

    private String generateOrderNo() {
        String ts = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"));
        int rand = ThreadLocalRandom.current().nextInt(1000, 9999);
        return "M" + ts + rand;
    }
}
